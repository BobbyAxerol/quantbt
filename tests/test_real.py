import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')
import sys
from pathlib import Path
sys.path.append(str(Path("/root/bobby/pool_alpha/alphas_storage/_get_data").resolve()))

from data_loader import CryptoBinance1m

perpetual_eth_re = CryptoBinance1m().load(
    symbols="ETHUSDT",
    check_val = True
)

perpetual_eth_re['datetime'] = pd.to_datetime(perpetual_eth_re['time'])
perpetual_eth_re = perpetual_eth_re[['datetime', 'open', 'high', 'low', 'close', 'volume']]
df_eth = perpetual_eth_re.copy()
df_eth = df_eth.sort_values('datetime').set_index('datetime')
data_eth = df_eth.resample('1h').agg({
    'open': 'first',
    'high': 'max',
    'low': 'min',
    'close': 'last',
    'volume': 'sum'
})


import numpy as np
import pandas as pd
from numba import njit

# =====================================================================
# 1. CÁC HÀM HỢP PHẦN CHỈ BÁO (INDICATORS)
# =====================================================================

@njit
def n_ema(src, length):
    alpha = 2.0 / (length + 1)
    out = np.zeros_like(src)
    out[0] = src[0]
    for i in range(1, len(src)):
        out[i] = alpha * src[i] + (1.0 - alpha) * out[i-1]
    return out

@njit
def n_sma(src, length):
    out = np.zeros_like(src)
    asum = 0.0
    for i in range(length):
        asum += src[i]
    out[length-1] = asum / length
    for i in range(length, len(src)):
        asum += src[i] - src[i-length]
        out[i] = asum / length
    return out

@njit
def n_macd(src, fast_len, slow_len, sig_len, is_sma_osc, is_sma_sig):
    fast_ma = n_sma(src, fast_len) if is_sma_osc else n_ema(src, fast_len)
    slow_ma = n_sma(src, slow_len) if is_sma_osc else n_ema(src, slow_len)
    macd_line = fast_ma - slow_ma
    signal_line = n_sma(macd_line, sig_len) if is_sma_sig else n_ema(macd_line, sig_len)
    return macd_line - signal_line

# =====================================================================
# 2. HÀM LOGIC BACKTEST LÕI (CORE LOGIC)
# =====================================================================

@njit
def core_scalping_forex_logic_unpacked(
    high, low, close, volume,
    initial_capital, cost,
    shortlen_obv, longlen_obv,
    psar_start, psar_inc, psar_max,
    ema_len, macd_fast, macd_slow, macd_sig,
    is_sma_osc, is_sma_sig
):
    n = len(close)
    pos_units = np.zeros(n)
    pos_weight = np.zeros(n)
    equity = np.zeros(n)
    equity[:] = initial_capital
    
    # Pre-calculate các chỉ báo nền tảng
    hist = n_macd(close, macd_fast, macd_slow, macd_sig, is_sma_osc, is_sma_sig)
    ema_200 = n_ema(close, ema_len)
    
    # Volume Oscillator kèm cơ chế phòng thủ chia cho 0
    short_v = n_ema(volume, shortlen_obv)
    long_v = n_ema(volume, longlen_obv)
    osc = np.zeros(n)
    for i in range(n):
        if long_v[i] != 0.0:
            osc[i] = 100.0 * (short_v[i] - long_v[i]) / long_v[i]

    # Quản lý trạng thái tài khoản và vị thế
    cash = initial_capital
    curr_units = 0.0
    target_w = 0.0  # Hướng vị thế mục tiêu: 1.0 (Long), -1.0 (Short), 0.0 (Flat)
    
    # Khởi tạo trạng thái Parabolic SAR
    sar = 0.0
    ep = 0.0
    af = psar_start
    uptrend = True
    
    tp_price = 0.0
    sl_price = 0.0
    
    if close[1] > close[0]:
        uptrend = True
        ep = high[1]
        sar = low[0]
    else:
        uptrend = False
        ep = low[1]
        sar = high[0]
    sar = sar + psar_start * (ep - sar)

    # ĐÃ SỬA: Xác định ngưỡng làm ấm chỉ báo (Warm-up Period) để chặn Fake Signals đầu chuỗi
    start_idx = max(ema_len, max(macd_fast, max(macd_slow, macd_sig)) + 10)
    start_idx = max(start_idx, max(shortlen_obv, longlen_obv))

    # Vòng lặp duyệt lịch sử nến
    for t in range(2, n):
        # Mặc định cập nhật tài sản bằng nến trước đó
        equity[t] = equity[t-1]
        
        # 2.1 CẬP NHẬT CHỈ BÁO PSAR KỸ THUẬT (Bắt buộc chạy liên tục từ t=2 để không gãy chuỗi)
        prev_sar = sar
        if uptrend:
            if prev_sar > low[t]:
                uptrend = False
                sar = max(ep, high[t])
                ep = low[t]
                af = psar_start
            else:
                if high[t] > ep:
                    ep = high[t]
                    af = min(af + psar_inc, psar_max)
                sar = prev_sar + af * (ep - prev_sar)
                sar = min(sar, low[t-1], low[t-2])
        else:
            if prev_sar < high[t]:
                uptrend = True
                sar = min(ep, low[t])
                ep = high[t]
                af = psar_start
            else:
                if low[t] < ep:
                    ep = low[t]
                    af = min(af + psar_inc, psar_max)
                sar = prev_sar + af * (ep - prev_sar)
                sar = max(sar, high[t-1], high[t-2])

        # Thiết lập điều kiện kỹ thuật đầu vào (Chỉ hiệu lực khi đã vượt qua giai đoạn Warm-up)
        long_cond = False
        short_cond = False
        if t >= start_idx:
            long_cond = (hist[t-1] < 0.0 and hist[t] > 0.0) and (close[t] > ema_200[t]) and uptrend and (osc[t] > 0.0)
            short_cond = (hist[t-1] > 0.0 and hist[t] < 0.0) and (close[t] < ema_200[t]) and (not uptrend) and (osc[t] > 0.0)

        # Cờ đánh dấu đóng vị thế trong nến
        exited_via_stop = False

        # 2.2 LOGIC QUẢN LÝ VỊ THẾ ĐANG CHẠY (POSITION MANAGEMENT)
        if target_w != 0.0:
            # KIỂM TRA THOÁT VỊ THẾ LONG
            if target_w == 1.0:
                # ĐÃ SỬA: Quét hộp giá Intraday (High/Low) và tất toán khớp đúng giá Stop lệnh điều kiện
                if low[t] <= sl_price:
                    cash += curr_units * sl_price * (1.0 - cost)
                    curr_units = 0.0
                    target_w = 0.0
                    exited_via_stop = True
                elif high[t] >= tp_price:
                    cash += curr_units * tp_price * (1.0 - cost)
                    curr_units = 0.0
                    target_w = 0.0
                    exited_via_stop = True
                elif short_cond:  # Thoát bằng tín hiệu đảo chiều tại Close nến
                    cash += curr_units * close[t] * (1.0 - cost)
                    curr_units = 0.0
                    target_w = 0.0
            
            # KIỂM TRA THOÁT VỊ THẾ SHORT
            elif target_w == -1.0:
                # ĐÃ SỬA: Quét hộp giá Intraday (High/Low) cho lệnh Short toán học chuẩn
                if high[t] >= sl_price:
                    cash += curr_units * sl_price * (1.0 + cost)
                    curr_units = 0.0
                    target_w = 0.0
                    exited_via_stop = True
                elif low[t] <= tp_price:
                    cash += curr_units * tp_price * (1.0 + cost)
                    curr_units = 0.0
                    target_w = 0.0
                    exited_via_stop = True
                elif long_cond:  # Thoát bằng tín hiệu đảo chiều tại Close nến
                    cash += curr_units * close[t] * (1.0 + cost)
                    curr_units = 0.0
                    target_w = 0.0

        # 2.3 LOGIC VÀO VỊ THẾ MỚI (ENTRY MANAGEMENT)
        # ĐÃ SỬA: Nếu vị thế vừa dính Stop Loss/Take Profit intraday, không cho phép mở lệnh lại trên cùng nến đó
        if target_w == 0.0 and not exited_via_stop and t >= start_idx:
            psar_dist = abs(close[t] - sar)
            
            if long_cond:
                target_w = 1.0
                curr_units = cash / (close[t] * (1.0 + cost))
                cash -= curr_units * close[t] * (1.0 + cost)
                tp_price = close[t] + psar_dist
                sl_price = close[t] - psar_dist
                
            elif short_cond:
                target_w = -1.0
                available_cash = max(0.0, cash)
                curr_units = -(available_cash / (close[t] * (1.0 + cost)))
                cash -= curr_units * close[t] * (1.0 - cost)
                tp_price = close[t] - psar_dist
                sl_price = close[t] + psar_dist

        # Ghi nhận trạng thái hướng vị thế (Direction) ra mảng đầu ra
        pos_weight[t] = target_w
        
        # Tính toán giá trị tài sản ròng thực tế cuối nến t
        equity[t] = cash + (curr_units * close[t])
        pos_units[t] = curr_units
        
    return pos_units, pos_weight, equity

# =====================================================================
# 3. HÀM WRAPPER GIAO TIẾP PYTHON ĐẦU VÀO
# =====================================================================

def backtest_scalping_forex(df, p):
    df = df.copy()
    h = df['high'].values.astype(np.float64)
    l = df['low'].values.astype(np.float64)
    c = df['close'].values.astype(np.float64)
    v = df['volume'].values.astype(np.float64)
    
    pos_units, pos_weight, equity = core_scalping_forex_logic_unpacked(
        h, l, c, v,
        p['initial_capital'], p.get('transaction_cost', 0.04) / 100.0,
        int(p['shortlen_obv']), int(p['longlen_obv']),
        p['psar_start'], p['psar_inc'], p['psar_max'],
        int(p['ema_len']), int(p['macd_fast']), int(p['macd_slow']), int(p['macd_sig']),
        p['is_sma_osc'], p['is_sma_sig']
    )
    
    df['pos_units'] = pos_units
    df['pos_weight'] = pos_weight
    df['equity'] = equity
    return df



baba = {'psar_start': 0.26, 'psar_inc': 0.34, 'psar_max': 0.1, 'macd_fast': 41, 'macd_slow': 45, 'macd_sig': 40, 'shortlen_obv': 46, 'longlen_obv': 37, 'ema_len': 140, 'is_sma_osc': False, 'is_sma_sig': False} # 1h eth, Ok nhé, số cũng oke lẫn đường cũng pass


base = {
    'initial_capital': 10000.0,
    'transaction_cost': 0.04,      # Phí sàn Binance (0.04%)       # Đi 50% vốn mỗi lệnh
}

hehe = {**baba, **base}

df_result = backtest_scalping_forex(data_eth, hehe)


import sys
sys.path.append('/root/bobby/pool_alpha')
from quantbt import BacktestEngine


import importlib
import quantbt as be_module
importlib.reload(be_module)
from quantbt import BacktestEngine

print("RELOADED & RE-IMPORTED!")


bt = BacktestEngine(
    Datetime        = df_result.index,
    Position        = df_result['pos_weight'],           # pd.Series: weights e.g. 1.0 / -0.5 / 0.0
    Close           = df_result['close'],
    High            = df_result['high'],       # optional, enables intrabar liq check
    Low             = df_result['low'],
    fee             = 0.0004,           # round-trip; halved internally to one-way
    use_pyramiding  = False,
    initial_capital = 20_000,
    leverage        = 5,
    maintenance_ratio = 0.005,
    contract_size   = 1.0,
    use_funding_rate = True,
    funding_rate    = 0.0001,
    alloc_per_trade = 0.5,
    hedge_type      = "%_equity",
    slippage        = 0.0001,       # 1 bp execution slippage
)

re = bt.analyze()     
# bt.tearsheet()               # full dashboard (optional)