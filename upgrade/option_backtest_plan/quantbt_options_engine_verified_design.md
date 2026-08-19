# QuantBT Options Engine

## Architecture Review, Formula Verification, Domain-Accurate Backtest Design, and Agent Implementation Guide

> **Mục tiêu:** bổ sung một engine backtest options chuyên biệt vào QuantBT theo hướng **add-on**, giữ nguyên tối đa những phần hiện tại đã đúng, chỉ sửa hoặc tách những phần có rủi ro sai domain, sai accounting, sai unit, hoặc không phù hợp với kiến trúc QuantBT hiện hành.
>
> **Phạm vi chính:** Deribit inverse options, Deribit linear USDC options, Binance European options, multi-leg package execution, delta hedging, lifecycle/settlement, multi-currency accounting, Greeks/P&L attribution, margin approximation, và một lớp validation tùy chọn bằng NautilusTrader.
>
> **Nguyên tắc quan trọng nhất:** một backtest options đúng không được tính P&L bằng một vài công thức payoff rời rạc. Engine phải mô phỏng nhất quán **instrument convention → quote convention → order/fill → premium cashflow → position valuation → hedge → fees → margin → expiry/settlement → reporting**.

---

## 1. Kết Luận Kiến Trúc Sau Khi Đối Chiếu QuantBT Hiện Tại

Thiết kế ban đầu có định hướng tổng thể tốt: tách data/schema, pricing/Greeks, execution, margin, lifecycle, analytics và Nautilus validation. Tuy nhiên, để thực sự phù hợp với QuantBT hiện tại và tránh phá vỡ các public contract đã có, kiến trúc nên được điều chỉnh theo các kết luận sau.

### 1.1 Những phần nên giữ nguyên

1. Giữ `QuantBTEndpoint` làm public facade duy nhất cho notebook và service.
2. Giữ sự phân tách giữa đường nghiên cứu nhanh và đường mô phỏng execution.
3. Giữ `OrderIntent`, `Fill`, `Trade`, `BacktestResultV2`, `AccountConfig`, `ExecutionConfig` làm domain primitive chung.
4. Giữ `ArbitrageSpec`, `ArbitrageLeg`, `ArbExecutionPolicy`, `PackageExecutionKind`, `HedgePolicy`, `LifecycleModel` làm nền tảng package/arbitrage hiện có.
5. Giữ `OptionsVolArbSpec` ở vai trò **schema cho volatility arbitrage**, không biến nó thành schema chung cho mọi chiến lược options.
6. Giữ Nautilus là lớp validation độc lập, không để Nautilus trở thành dependency bắt buộc của native engine.
7. Giữ hot loop ở NumPy/Numba và chuyển object Python thành contiguous arrays trước khi mô phỏng.
8. Giữ kết quả cuối tương thích với `BacktestResultV2` để toàn bộ metrics, plotting, report bundle và endpoint helper hiện có tiếp tục hoạt động.

### 1.2 Những phần cần sửa hoặc thiết kế lại

1. **Không nên đặt toàn bộ strategy implementation trong `quantbt/strategies/`.** Repo hiện tại không dùng QuantBT như một framework chứa strategy class nội bộ; QuantBT chủ yếu nhận signal, target position, basket hoặc explicit orders từ bên ngoài. Options engine nên cung cấp các **selector, package builder và strategy template**, nhưng không ép mọi chiến lược kế thừa một `BaseOptionStrategy` nằm trong core.
2. **Không nên dùng dense tensor cố định** dạng `N_bars × N_contracts` cho toàn bộ option chain. Contract được list/delist liên tục, expiry thay đổi, strike universe không cố định và dữ liệu cực kỳ sparse. Cần dùng long-form canonical data và compile thành ragged/CSR event tape.
3. **Không nên cho generic `native_event` chạy trực tiếp options** chỉ bằng cách thêm vài branch. Current event backend dùng OHLC bars, linear notional và scalar fee rate; options cần quote-side execution, multi-currency cashflow, premium settlement, lifecycle và Greek-aware risk. Cần backend chuyên biệt.
4. **Không nên tạo enum execution mới trùng ý nghĩa.** QuantBT hiện đã có:
   - `ATOMIC_ALL_OR_NONE`
   - `BEST_EFFORT`
   - `SEQUENTIAL`
   - `HEDGE_AFTER_PRIMARY`
   - `REBALANCE_ONLY`

   Options engine nên reuse đúng các enum này.
5. **Không nên hard-code Deribit Portfolio Margin bằng một ma trận nhỏ cố định.** Mô hình hiện tại của Deribit có main table, underlying buckets, volatility up/same/down, extended table, roll shock, delta shock và nhiều adjustment động. Native engine chỉ nên cung cấp một scenario approximation được version hóa; exact venue validation dùng API mô phỏng margin hoặc Nautilus/venue adapter.
6. **Không được dùng cùng một Black-76 kernel cho linear và inverse options.** Quote currency, payoff currency, delta/gamma unit và P&L conversion khác nhau.
7. **Không được dùng option fee của inverse contract theo USD rồi so với premium BTC.** Hai nhánh của hàm `min()` phải cùng currency.
8. **Không được tính cumulative P&L thủ công rồi đồng thời mark position value**, vì rất dễ double-count premium, hedge P&L hoặc fee. Nguồn sự thật phải là ledger và equity identity.

### 1.3 Kết luận ngắn gọn

Kiến trúc đúng nhất là:

```text
QuantBTEndpoint.options(...)
          │
          ▼
OptionBacktestEngine
          │
          ├── OptionResearchKernel
          │     ├── selectors
          │     ├── IV / Greeks
          │     ├── surface
          │     └── fast signal/package preparation
          │
          └── NativeOptionBackend
                ├── quote/event tape
                ├── package execution
                ├── multi-currency ledger
                ├── hedge policy
                ├── margin policy
                ├── expiry/settlement
                └── BacktestResultV2-compatible output
```

Đây là một **specialized backend** nằm cạnh `native_vectorized`, `native_event` và `native_portfolio`, không phải một patch lớn nhồi logic options vào các kernel hiện hữu.

---

## 2. Đối Chiếu Với Cấu Trúc QuantBT Hiện Tại

QuantBT hiện đã có các thành phần rất phù hợp để mở rộng:

| Thành phần hiện tại | Vai trò hiện tại | Cách dùng cho options |
|---|---|---|
| `core/schema.py` | Instrument/account/execution schema chung | Chỉ thêm `AssetType.OPTION`; option-specific fields đặt ở package mới |
| `core/orders.py` | `OrderIntent`, `Fill`, `Trade` | Reuse làm leaf orders/fills sau khi package compiler xử lý |
| `core/arbitrage.py` | Multi-leg specs, package policy, lifecycle policy | Reuse enum/policy; giữ `OptionsVolArbSpec` cho vol arb thực sự |
| `core/order_compiler.py` | Compile immutable intents thành ndarray | Tạo compiler tương tự cho option quote/event tape |
| `backends/native_event.py` | OHLC event simulation | Dùng làm reference pattern, không dùng làm option execution kernel trực tiếp |
| `backends/native_vectorized.py` | Fast signal research | Dùng triết lý prepared arrays/Numba cho selector và analytics |
| `core/results.py` | `BacktestResultV2` | Trả subclass hoặc object tương thích với các field mở rộng có default |
| `engines.py` | Engine facade | Thêm `OptionBacktestEngine`, không làm phình `BacktestEngineV2` quá mức |
| `endpoint.py` | Stable public API | Thêm `QuantBTEndpoint.options(...)` và support matrix |
| `adapters/nautilus/` | Optional third-party validation | Thêm option adapter sau khi native accounting đã ổn định |

### 2.1 Điểm đặc biệt quan trọng trong repo hiện tại

`OptionsVolArbSpec` hiện được khai báo nhưng generic package route cố tình không execute vì cần specialized option/Greeks engine. Đây là quyết định kiến trúc đúng. Engine mới nên hoàn thành đúng “reserved extension point” đó thay vì thay đổi hành vi của generic package backend một cách âm thầm.

### 2.2 Vì sao không dùng `OptionsVolArbSpec` cho mọi strategy

Base `ArbitrageSpec` yêu cầu ít nhất hai legs và `OptionsVolArbSpec` chỉ chấp nhận hedge policy `DELTA_NEUTRAL` hoặc `VEGA_NEUTRAL`. Điều này phù hợp với volatility arbitrage nhưng không phù hợp với:

- long call directional;
- protective put;
- covered call;
- cash-secured put;
- collar;
- vertical spread directional;
- tail hedge;
- event-driven convexity bet;
- option overlay trên một portfolio có sẵn.

Do đó cần một `OptionPackageIntent` hoặc `OptionStrategySpec` chung, còn `OptionsVolArbSpec` giữ nguyên cho một subset chuyên biệt.

---

## 3. Kiến Trúc Package Đề Xuất

```text
quantbt/
├── core/
│   ├── schema.py                    # ADD: AssetType.OPTION only
│   ├── orders.py                    # KEEP: generic leaf OrderIntent / Fill
│   ├── arbitrage.py                 # KEEP: existing enums and OptionsVolArbSpec
│   └── results.py                   # ADDITIVE: optional result fields/subclass
│
├── options/                         # NEW: domain package
│   ├── __init__.py
│   ├── schema.py                    # OptionInstrumentSpec, quote/settlement enums
│   ├── conventions.py               # Deribit/Binance venue rules, versioned
│   ├── data.py                      # canonical long-form schemas
│   ├── tape.py                      # ragged/CSR compiled option event tape
│   ├── pricing.py                   # linear Black-76, inverse Black, intrinsic
│   ├── iv.py                        # robust IV inversion and no-arb bounds
│   ├── greeks.py                    # normalized Greek units and finite-diff checks
│   ├── surface.py                   # raw SVI/SSVI calibration and validation
│   ├── selectors.py                 # ATM, delta, moneyness, DTE, liquidity selector
│   ├── packages.py                  # OptionPackageIntent and compiler
│   ├── execution.py                 # bid/ask/depth/package execution
│   ├── ledger.py                    # multi-currency cash and position accounting
│   ├── fees.py                      # per-venue fee model
│   ├── margin.py                    # standard/scenario/external margin interfaces
│   ├── lifecycle.py                 # expiry, delivery, auto exercise, roll
│   ├── hedging.py                   # threshold/time/hysteresis/optional WW policy
│   ├── attribution.py               # delta/gamma/theta/vega/vanna/volga residual
│   └── templates/                   # optional package builders, not engine subclasses
│       ├── volatility.py
│       ├── spreads.py
│       ├── overlays.py
│       ├── relative_value.py
│       └── arbitrage.py
│
├── backends/
│   └── native_option.py             # NEW: specialized event backend
│
├── metrics/
│   └── options_analytics.py         # NEW: option-specific reports
│
├── adapters/
│   └── nautilus/
│       └── options.py               # LATER: version-pinned validation adapter
│
├── examples/
│   └── options/
│       ├── deribit_gamma_scalping.py
│       ├── calendar_spread.py
│       ├── covered_call.py
│       └── cross_venue_vol.py
│
└── tests/
    └── options/
        ├── test_pricing.py
        ├── test_inverse_conventions.py
        ├── test_iv.py
        ├── test_packages.py
        ├── test_execution.py
        ├── test_ledger.py
        ├── test_lifecycle.py
        ├── test_margin.py
        ├── test_attribution.py
        └── test_endpoint_contract.py
```

### 3.1 Tại sao nên có top-level `options/`

- `core/` hiện chứa primitive dùng chung, không nên biến thành một thư mục domain-specific quá lớn.
- Options có đủ schema, pricing, lifecycle, margin, venue conventions và data model riêng để trở thành bounded context độc lập.
- `backends/native_option.py` có thể import từ `options/` mà không làm generic core phụ thuộc vào Deribit/Binance.
- Sau này có thể thêm futures options, equity options hoặc volatility products mà không sửa các kernel spot/perp hiện tại.

---

## 4. Public API Phù Hợp Với QuantBT

### 4.1 Endpoint mới

```python
bt = QuantBTEndpoint.options(
    backend="native_option",
    simulation_mode="event",
    venue="deribit",
    initial_capital=2.0,
    base_currency="BTC",
    reporting_currency="USD",
    margin_mode="portfolio",
    mark_policy="venue_mark",
    stale_quote_ns=5_000_000_000,
)

result = bt.simulate(
    chain=option_chain,
    underlying=underlying_tape,
    packages=package_intents,
    instruments=instrument_specs,
)
```

### 4.2 Research mode

```python
research = QuantBTEndpoint.options(
    backend="native_option",
    simulation_mode="research",
    venue="deribit",
)

selection = research.select_contracts(
    chain=option_chain,
    target_dte=30,
    target_delta=0.25,
    max_spread_bps=500,
    min_open_interest=100,
)
```

`research` mode chỉ dùng để:

- scan chain;
- tính IV/Greeks/surface;
- build package candidates;
- parameter sweep;
- approximate mark-to-market research.

Nó **không được quảng cáo là execution-accurate** nếu không chạy qua event mode.

### 4.3 Endpoint support matrix đề xuất

```python
{
    "options": {
        "native_option": "supported",
        "native_event": "unsupported_directly",
        "native_vectorized": "analytics_only",
        "nautilus": "validation_planned_or_experimental",
    },
    "OptionsVolArbSpec": {
        "native_option": "supported_specialized",
        "native_event": "schema_only",
        "native_vectorized": "schema_only",
    },
}
```

Không nên sửa generic `arbitrage_support_matrix()` thành “supported everywhere”. Thay vào đó, route phải nói rõ `OptionsVolArbSpec` được execute bởi specialized option engine.

---

## 5. Domain Schema Chuẩn Cho Option Instrument

### 5.1 Thêm enum tối thiểu vào core

```python
class AssetType(str, Enum):
    CRYPTO = "crypto"
    STOCK = "stock"
    FUTURE = "future"
    FX = "fx"
    OPTION = "option"
```

### 5.2 Option-specific schema tách riêng

```python
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from quantbt.core.schema import AssetType, InstrumentSpec


class OptionKind(str, Enum):
    CALL = "call"
    PUT = "put"


class ExerciseStyle(str, Enum):
    EUROPEAN = "european"
    AMERICAN = "american"


class PremiumConvention(str, Enum):
    LINEAR_QUOTE = "linear_quote"
    INVERSE_BASE = "inverse_base"
    QUANTO = "quanto"


class SettlementStyle(str, Enum):
    CASH = "cash"
    FUTURE_THEN_CASH = "future_then_cash"
    PHYSICAL = "physical"


@dataclass(frozen=True, kw_only=True)
class OptionInstrumentSpec(InstrumentSpec):
    asset_type: AssetType = AssetType.OPTION

    venue: str
    underlying_id: str
    underlying_index_id: str
    option_kind: OptionKind
    exercise_style: ExerciseStyle
    premium_convention: PremiumConvention
    settlement_style: SettlementStyle

    strike: float
    expiry_ns: int
    settlement_currency: str
    premium_currency: str
    quote_currency: str

    multiplier: float = 1.0
    settlement_time_ns: Optional[int] = None
    fee_schedule_id: str = ""
    margin_schedule_id: str = ""
    convention_version: str = ""
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.asset_type is not AssetType.OPTION:
            raise ValueError("OptionInstrumentSpec.asset_type must be OPTION")
        if not self.venue:
            raise ValueError("venue is required")
        if not self.underlying_id or not self.underlying_index_id:
            raise ValueError("underlying identifiers are required")
        if self.strike <= 0.0:
            raise ValueError("strike must be > 0")
        if self.expiry_ns <= 0:
            raise ValueError("expiry_ns must be > 0")
        if self.multiplier <= 0.0:
            raise ValueError("multiplier must be > 0")
        if not self.premium_currency or not self.settlement_currency:
            raise ValueError("premium and settlement currencies are required")
```

### 5.3 Vì sao cần các field này

Một symbol như `BTC-27DEC26-100000-C` chưa đủ để tính đúng backtest. Engine phải biết:

- premium được quote bằng BTC hay USDC;
- payoff được settle bằng BTC, ETH, USDC hay thông qua expiry future;
- multiplier là 1 BTC, 1 ETH, 10 SOL hay giá trị khác;
- quantity step và minimum quantity;
- mark/fill price đang mang unit nào;
- fee trả bằng currency nào;
- forward/index nào được dùng để tính IV;
- phiên bản rule nào áp dụng tại timestamp lịch sử.

Nếu thiếu các field này, cùng một công thức có thể cho kết quả sai 100 lần hoặc sai currency hoàn toàn.

---

## 6. Data Model: Không Dùng Dense `N_bars × N_contracts`

### 6.1 Canonical long-form chain

Dữ liệu lưu trữ chuẩn nên là một bảng long-form:

```text
timestamp_ns
instrument_id
venue
underlying_id
expiry_ns
strike
option_kind
bid_price
bid_size
ask_price
ask_size
mark_price
last_price
index_price
forward_price
mark_iv
bid_iv
ask_iv
delta
gamma
vega
theta
open_interest
volume
quote_currency
settlement_currency
sequence_id
source_latency_ns
```

### 6.2 Compiled ragged tape cho hot loop

Khi backtest, chuyển bảng long-form thành cấu trúc giống CSR:

```python
@dataclass(frozen=True)
class CompiledOptionTape:
    snapshot_ts_ns: np.ndarray       # [N_snapshots]
    row_ptr: np.ndarray              # [N_snapshots + 1]

    instrument_code: np.ndarray      # [N_quotes]
    bid: np.ndarray                  # [N_quotes]
    ask: np.ndarray                  # [N_quotes]
    bid_size: np.ndarray             # [N_quotes]
    ask_size: np.ndarray             # [N_quotes]
    mark: np.ndarray                 # [N_quotes]
    mark_iv: np.ndarray              # [N_quotes]
    open_interest: np.ndarray        # [N_quotes]

    index_price: np.ndarray          # [N_snapshots]
    forward_price: np.ndarray        # [N_snapshots]
```

Snapshot `i` chứa quotes trong khoảng:

$$
\left[\text{row\_ptr}_i,\;\text{row\_ptr}_{i+1}\right).
$$

### 6.3 Lợi ích

- không lặp strike/DTE cho mọi bar;
- không tạo hàng triệu ô `NaN` cho contract chưa tồn tại hoặc đã expiry;
- không có survivorship bias do ép chain về một universe cố định;
- dễ append real-time data;
- dễ reject quote stale;
- dễ compile sang Numba;
- có thể giữ sequence/order-book semantics.

### 6.4 DTE phải tính từ timestamp thực

Không nên dùng mặc định:

$$
T = \frac{\mathrm{DTE}}{365}.
$$

Nên dùng:

$$
\tau_t
= \max\left(
\frac{t_{\mathrm{expiry}} - t}{365.0 \times 24 \times 3600},
0
\right),
$$

với timestamp theo UTC và độ chính xác tối thiểu là giây; tốt nhất dùng nanosecond integer trong hot loop.

### 6.5 Data-quality guards bắt buộc

Một quote chỉ hợp lệ nếu:

$$
0 < \mathrm{bid} \leq \mathrm{ask},
$$

và:

$$
\frac{\mathrm{ask}-\mathrm{bid}}
{\tfrac{1}{2}(\mathrm{ask}+\mathrm{bid})}
\leq s_{\max}.
$$

Ngoài ra cần kiểm tra:

- timestamp monotonic;
- duplicate sequence;
- crossed book;
- quote stale;
- expiry đã qua;
- strike/multiplier khác metadata;
- impossible IV;
- price ngoài no-arbitrage bounds;
- missing index/forward;
- currency mismatch;
- settlement event thiếu delivery price.

---

## 7. Quy Tắc Chống Lookahead Bias

Options chain có rủi ro lookahead lớn hơn OHLC backtest thông thường.

### 7.1 Quy tắc snapshot

Tại decision time $t$:

1. Strategy chỉ được đọc quote có `quote_timestamp <= t`.
2. Nếu signal dùng close của bar $t$, fill mặc định phải ở snapshot đầu tiên sau khi bar đóng, không được fill tại quote trước close.
3. Nếu signal dùng quote tick tại $t$, same-timestamp fill chỉ được phép khi engine mô hình hóa rõ sequencing bằng `sequence_id`.
4. Selection theo delta/IV phải dùng delta/IV observable tại thời điểm chọn, không được dùng Greek recomputed từ settlement price tương lai.
5. Contract roll chỉ được chọn từ instrument universe đã được list tại thời điểm đó.
6. Delivery price chỉ xuất hiện tại expiry event; không được dùng TWAP cuối cùng trước khi toàn bộ TWAP window hoàn tất.

### 7.2 Decision/fill policy đề xuất

```python
class OptionDecisionFillPolicy(str, Enum):
    NEXT_SNAPSHOT = "next_snapshot"
    SAME_SNAPSHOT_AFTER_SIGNAL = "same_snapshot_after_signal"
    NEXT_BAR_OPEN = "next_bar_open"
    EXPLICIT_EVENT_SEQUENCE = "explicit_event_sequence"
```

Default production-safe nên là `NEXT_SNAPSHOT`.

---

## 8. Pricing Kernel: Linear Black-76

### 8.1 Ký hiệu chuẩn

- $F$: forward/futures price tới expiry;
- $K$: strike;
- $\tau$: time to expiry theo năm;
- $r$: continuously compounded discount rate;
- $D = e^{-r\tau}$: discount factor;
- $\sigma$: implied volatility ở decimal unit, ví dụ $0.60$, không phải $60$;
- $\Phi$: standard normal CDF;
- $\phi$: standard normal PDF.

$$
d_1
=
\frac{
\ln(F/K)+\tfrac{1}{2}\sigma^2\tau
}{
\sigma\sqrt{\tau}
},
\qquad
 d_2=d_1-\sigma\sqrt{\tau}.
$$

### 8.2 Linear call và put

$$
C_{\mathrm{lin}}
=
D\left[F\Phi(d_1)-K\Phi(d_2)\right],
$$

$$
P_{\mathrm{lin}}
=
D\left[K\Phi(-d_2)-F\Phi(-d_1)\right].
$$

Đây là premium theo quote/settlement currency trước khi nhân multiplier và quantity.

### 8.3 Greeks theo forward

$$
\Delta_F^{C}=D\Phi(d_1),
\qquad
\Delta_F^{P}=-D\Phi(-d_1),
$$

$$
\Gamma_F
=
\frac{D\phi(d_1)}{F\sigma\sqrt{\tau}},
$$

$$
\mathrm{Vega}_{\mathrm{abs}}
=
DF\phi(d_1)\sqrt{\tau}.
$$

`Vega_abs` là P&L khi volatility thay đổi `1.0`, tức 100 volatility points. Nếu muốn vega theo một volatility point:

$$
\mathrm{Vega}_{1\mathrm{pt}}
=
\frac{\mathrm{Vega}_{\mathrm{abs}}}{100}.
$$

Engine nội bộ nên dùng `vega_abs`; reporting mới convert sang `vega_1pt`. Nếu dùng `vega/100` trong kernel nhưng lại nhân với $\Delta\sigma$ ở decimal, attribution sẽ sai hệ số 100.

### 8.4 Theta Black-76

Nếu $F$ và $\sigma$ được giữ cố định khi lấy partial derivative theo calendar time:

$$
\Theta
=
 rV
-
\frac{DF\phi(d_1)\sigma}{2\sqrt{\tau}},
$$

trong đó $V$ là call hoặc put value. Công thức theta trong bản thiết kế cũ đã trộn Black-Scholes spot theta với Black-76 và không nên dùng.

### 8.5 Numba implementation an toàn

Không nên phụ thuộc vào `np.erf`. Dùng `math.erf`, được Numba hỗ trợ ổn định hơn.

```python
from math import erf, exp, log, pi, sqrt
from numba import njit

SQRT_2 = sqrt(2.0)
SQRT_2PI = sqrt(2.0 * pi)


@njit(cache=True)
def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + erf(x / SQRT_2))


@njit(cache=True)
def norm_pdf(x: float) -> float:
    return exp(-0.5 * x * x) / SQRT_2PI
```

Không nên bật `fastmath=True` mặc định cho IV inversion, tail probability hoặc no-arbitrage validation. Có thể bật riêng cho batch pricing sau khi parity tests chứng minh sai số chấp nhận được.

---

## 9. Inverse Option Pricing Và Settlement

Deribit inverse BTC/ETH options được quote bằng base currency. Đây không chỉ là linear premium chia cho spot ở cuối backtest; convention ảnh hưởng trực tiếp tới mark, Greeks, fee và account equity.

### 9.1 Payoff tại expiry theo base currency

Với delivery price $S_T$:

$$
C_{\mathrm{inv},T}
=
\frac{\max(S_T-K,0)}{S_T}
=
\max\left(1-\frac{K}{S_T},0\right),
$$

$$
P_{\mathrm{inv},T}
=
\frac{\max(K-S_T,0)}{S_T}
=
\max\left(\frac{K}{S_T}-1,0\right).
$$

Sau đó nhân:

$$
\mathrm{SettlementCashflow}
=
q \times M \times \mathrm{Payoff},
$$

trong đó $q$ là signed quantity và $M$ là contract multiplier.

### 9.2 Inverse Black price theo base currency

Một convention nhất quán với forward-based implied volatility là:

$$
C_{\mathrm{inv}}
=
D\left[
\Phi(d_1)-\frac{K}{F}\Phi(d_2)
\right],
$$

$$
P_{\mathrm{inv}}
=
D\left[
\frac{K}{F}\Phi(-d_2)-\Phi(-d_1)
\right].
$$

Tại expiry, $F \rightarrow S_T$, $D \rightarrow 1$, các công thức hội tụ về inverse intrinsic payoff.

### 9.3 Hai hệ Greek khác nhau

Engine phải phân biệt:

1. **settlement-currency Greeks**: thay đổi premium BTC/ETH khi $F$ thay đổi;
2. **reporting-currency Greeks**: thay đổi USD value của position sau khi quy đổi coin value sang USD.

Nếu premium base-currency là $V_b(F)$ và reporting value là:

$$
V_q(F)=F\,V_b(F),
$$

thì:

$$
\frac{\partial V_q}{\partial F}
=
V_b(F)+F\frac{\partial V_b}{\partial F}.
$$

Do đó không thể lấy linear delta và gán thẳng cho BTC-denominated P&L, cũng không thể lấy inverse base delta để hedge một USD risk target mà không conversion.

### 9.4 Put-call parity cho inverse quote

Trong base currency:

$$
C_{\mathrm{inv}}-P_{\mathrm{inv}}
=
D\left(1-\frac{K}{F}\right).
$$

Nhân hai vế với $F$:

$$
F\left(C_{\mathrm{inv}}-P_{\mathrm{inv}}\right)
=
D(F-K).
$$

Parity/arbitrage engine phải dùng đúng convention này thay vì áp dụng trực tiếp:

$$
C-P=S-Ke^{-rT}
$$

cho mọi venue và mọi settlement currency.

---

## 10. IV Solver Và No-Arbitrage Bounds

### 10.1 Linear bounds

Call:

$$
D\max(F-K,0)
\leq C
\leq DF.
$$

Put:

$$
D\max(K-F,0)
\leq P
\leq DK.
$$

### 10.2 Inverse bounds

Call:

$$
D\max\left(1-\frac{K}{F},0\right)
\leq C_{\mathrm{inv}}
\leq D.
$$

Put:

$$
D\max\left(\frac{K}{F}-1,0\right)
\leq P_{\mathrm{inv}}
\leq D\frac{K}{F}.
$$

### 10.3 Solver đề xuất

- reject price ngoài bounds;
- bracket volatility trong `[1e-6, 8.0]` hoặc venue-configurable range;
- dùng Brent hoặc bisection làm baseline deterministic;
- Newton chỉ dùng sau khi bracket đã tồn tại;
- không solve IV từ zero bid;
- lưu `iv_status`: `ok`, `below_intrinsic`, `above_upper_bound`, `no_bracket`, `stale`, `missing_forward`;
- bid IV và ask IV solve riêng;
- mark IV không được tự động thay bid/ask IV trong execution.

---

## 11. Volatility Surface: SVI Đúng Nhưng Chưa Đủ

Raw SVI total variance cho một expiry:

$$
w(k)
=
a+b\left[
\rho(k-m)+\sqrt{(k-m)^2+\sigma^2}
\right],
$$

với:

$$
k=\ln\left(\frac{K}{F}\right),
\qquad
w(k)=\sigma_{\mathrm{imp}}^2(k,\tau)\,\tau.
$$

Công thức này đúng. Tuy nhiên, chỉ fit năm tham số không có nghĩa surface đã arbitrage-free.

### 11.1 Basic parameter guards

$$
b \geq 0,
\qquad
|\rho|<1,
\qquad
\sigma>0,
$$

và minimum total variance phải không âm:

$$
a+b\sigma\sqrt{1-\rho^2}\geq 0.
$$

### 11.2 Static-arbitrage checks bắt buộc

1. butterfly arbitrage trên mỗi expiry;
2. calendar arbitrage giữa các expiry;
3. monotonic total variance theo maturity ở fixed log-moneyness;
4. positive density hoặc Durrleman condition;
5. extrapolation wing constraints;
6. stable interpolation trong total variance, không interpolate trực tiếp IV tùy tiện.

### 11.3 Roadmap surface

- Phase 1: linear interpolation theo delta/log-moneyness + no-arb bounds;
- Phase 2: raw SVI từng expiry + validation;
- Phase 3: SSVI/eSSVI global surface;
- Phase 4: local-vol/density analytics nếu thực sự cần.

Không nên để SVI calibration block execution engine. Surface là analytics service có cache; execution luôn ưu tiên observed bid/ask/mark.

---

## 12. Contract Selection Engine

Selector phải là reusable, deterministic và độc lập strategy.

```python
@dataclass(frozen=True)
class OptionSelectionRequest:
    timestamp_ns: int
    underlying_id: str
    option_kind: OptionKind | None = None
    target_expiry_ns: int | None = None
    target_dte_days: float | None = None
    target_delta: float | None = None
    target_moneyness: float | None = None
    target_strike: float | None = None
    min_open_interest: float = 0.0
    min_quote_size: float = 0.0
    max_spread_bps: float = float("inf")
    max_quote_age_ns: int = 5_000_000_000
```

### 12.1 Selection order đề xuất

1. filter venue/underlying;
2. filter active instruments;
3. filter expiry window;
4. filter option kind;
5. filter valid two-sided quote;
6. filter stale/spread/OI/size;
7. rank theo target delta hoặc log-moneyness;
8. tie-break theo spread, OI, quote size, instrument ID;
9. trả cả selected contract và diagnostics.

### 12.2 25-delta convention

- Call target: $\Delta \approx +0.25$.
- Put target: $\Delta \approx -0.25$.
- Long 25-delta call + short 25-delta put có directional delta dương đáng kể; nó không tự nhiên delta-neutral.
- Một skew-only risk reversal cần hedge underlying hoặc size theo một risk target rõ ràng.

---

## 13. Multi-Leg Package Domain

### 13.1 Không trộn `side` với signed ratio

Trong thiết kế cũ, ví dụ “ratio +1 cho call, -1 cho put” đồng thời có `side`. Điều này dễ tạo hai nguồn sign trái nhau. Nên quy định:

- `side` chứa direction;
- `ratio` luôn dương;
- package quantity luôn dương;
- signed quantity chỉ được tính tại compiler.

```python
@dataclass(frozen=True)
class OptionPackageLeg:
    instrument_id: str
    side: OrderSide
    ratio: float
    role: str
    order_type: OrderType = OrderType.MARKET
    limit_price: float | None = None
    reduce_only: bool = False
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.ratio <= 0.0:
            raise ValueError("ratio must be > 0; direction belongs to side")
```

### 13.2 Package intent

```python
@dataclass(frozen=True)
class OptionPackageIntent:
    timestamp_ns: int
    package_id: str
    legs: tuple[OptionPackageLeg, ...]
    package_qty: float
    execution_policy: ArbExecutionPolicy
    hedge_policy: HedgePolicy | None = None
    lifecycle_policy: LifecycleModel | None = None
    max_package_debit: float | None = None
    min_package_credit: float | None = None
    max_total_slippage_bps: float | None = None
    metadata: dict = field(default_factory=dict)
```

Compiler chuyển package thành leaf `OrderIntent` và đặt metadata:

```python
{
    "package_id": "...",
    "leg_role": "long_call",
    "leg_index": 0,
    "package_execution_kind": "atomic_all_or_none",
    "premium_currency": "BTC",
}
```

### 13.3 Execution modes reuse từ QuantBT

#### `ATOMIC_ALL_OR_NONE`

1. Snapshot toàn bộ legs tại cùng event time.
2. Pre-calculate side-aware executable prices.
3. Pre-check depth/size/quantity constraints.
4. Pre-check package debit/credit.
5. Pre-check margin sau trade.
6. Nếu bất kỳ leg fail, rollback toàn bộ.
7. Chỉ commit fills và ledger khi tất cả pass.

Atomic trong backtest không có nghĩa các venue thật hỗ trợ native combo order. Metadata phải nói rõ:

```text
atomicity_source = "exchange_combo" | "simulated_snapshot" | "block_trade"
```

#### `BEST_EFFORT`

- cho phép partial package;
- phải ghi residual risk;
- không được tự động gọi partial package là spread hoàn chỉnh;
- margin và Greek exposure cập nhật sau từng fill.

#### `SEQUENTIAL`

- xác định leg priority;
- execute leg khó/liquid thấp trước hoặc theo config;
- giữ legging exposure giữa các fill;
- có timeout/unwind policy;
- tính slippage và adverse move trong khoảng legging.

#### `HEDGE_AFTER_PRIMARY`

- fill primary option leg/package;
- recompute portfolio delta theo account-currency risk;
- gửi hedge order spot/perp;
- nếu hedge fail, giữ residual delta và áp dụng emergency policy.

#### `REBALANCE_ONLY`

- không mở mới option package;
- chỉ chỉnh hedge hoặc Greek target của package đang tồn tại.

---

## 14. Fill Model Cho Options

### 14.1 Side-aware executable price

Cho marketable order không có depth model:

$$
P_{\mathrm{buy}}=\mathrm{ask},
\qquad
P_{\mathrm{sell}}=\mathrm{bid}.
$$

Không dùng `mark` hoặc `mid` làm fill mặc định.

### 14.2 Mark policy và liquidation policy phải tách nhau

- `venue_mark`: dùng mark price venue cung cấp;
- `mid`: dùng valid two-sided midpoint;
- `model`: dùng model value khi quote thiếu, chỉ cho diagnostics hoặc configurable fallback;
- `liquidation_value`: long close ở bid, short close ở ask.

Equity có thể report cả hai:

```text
mark_equity
liquidation_equity
```

### 14.3 Depth và partial fill

Nếu có L2 data:

$$
\mathrm{VWAP}(Q)
=
\frac{\sum_j p_j q_j}{\sum_j q_j},
$$

với $\sum_j q_j=Q$ hoặc available depth. Nếu không đủ depth:

- FOK/AON: reject;
- IOC: partial rồi cancel remainder;
- GTC: giữ remainder trong order state;
- market order: configurable reject hoặc impact extrapolation.

### 14.4 Maker fill

Một limit order chạm price không tự động có nghĩa được fill. Cần ít nhất ba fidelity levels:

1. `touch_fill`: optimistic;
2. `trade_through_fill`: conservative;
3. `queue_model`: dùng trade/depth/queue estimate.

Metadata result phải lưu fidelity level.

---

## 15. Multi-Currency Ledger: Nguồn Sự Thật Của P&L

### 15.1 State tối thiểu

```python
cash[currency]
position_qty[instrument_id]
avg_entry_price[instrument_id]
realized_pnl[currency]
fees[currency]
settlement_cashflows[currency]
margin_locked[currency]
```

### 15.2 Premium cashflow

Với signed quantity $q$ và premium $P$ trong premium currency:

$$
\mathrm{PremiumCashflow}
=
-q \times M \times P.
$$

- Long option: $q>0$, cashflow âm.
- Short option: $q<0$, cashflow dương.

Fee được ghi riêng, không nhúng vào fill price trừ khi venue thật sự quote all-in.

### 15.3 Mark value

$$
\mathrm{PositionValue}_{i,t}^{(c)}
=
q_i M_i V_{i,t}^{(c)}.
$$

### 15.4 Equity theo reporting currency

$$
\mathrm{Equity}_t^{(R)}
=
\sum_c \mathrm{Cash}_t^{(c)}\,X_{c\rightarrow R,t}
+
\sum_i \mathrm{PositionValue}_{i,t}^{(c_i)}\,X_{c_i\rightarrow R,t}.
$$

Trong đó $X_{c\rightarrow R,t}$ là FX/index conversion rate tại thời điểm $t$.

### 15.5 Accounting invariant

Mỗi bar/event phải thỏa:

$$
\mathrm{Equity}_t
=
\mathrm{Equity}_{t-1}
+
\mathrm{TradingPnL}_t
+
\mathrm{Carry}_t
+
\mathrm{Settlement}_t
-
\mathrm{Fees}_t.
$$

Sai số residual sau conversion chỉ được nằm trong tolerance đã định nghĩa.

### 15.6 Không tính cumulative P&L thủ công

Đoạn gamma-scalping cũ có các lỗi phổ biến:

- entry premium có thể bị trừ rồi option MTM lại trừ entry lần nữa;
- realized hedge P&L có thể được cộng vào `cum_hedge_pnl` rồi cộng lại một lần nữa;
- unrealized hedge P&L giữa hai lần rebalance bị bỏ sót;
- hedge quantity mới có thể bị dùng cho price move đã xảy ra trước khi lệnh hedge được fill;
- `df_perp_ticks` được truyền vào nhưng không thực sự dùng;
- combined straddle fee cap áp dụng sai thay vì per-leg;
- USD fee và BTC premium được so trong cùng một `min()`.

Ledger-centric engine loại bỏ toàn bộ nhóm lỗi này.

---

## 16. Correct Event Ordering Cho Gamma Hedging

Tại mỗi event $t$:

1. advance clock;
2. ingest underlying quote/index/forward;
3. ingest option quotes;
4. process pending fills theo event sequence;
5. process expiry/delivery event nếu có;
6. accrue funding/borrow/interest;
7. mark existing positions;
8. compute pre-trade equity/margin/Greeks;
9. strategy reads observable state và tạo intents;
10. execute option package;
11. recompute Greeks;
12. execute hedge policy;
13. charge fees/slippage;
14. recompute post-trade cash, positions, margin, mark equity và liquidation equity;
15. append audit row.

### 16.1 Hedge P&L đúng theo discrete time

Nếu hedge quantity trước trade tại $t$ là $h_{t-1}$:

$$
\mathrm{HedgePnL}_t
=
h_{t-1}\left(H_t-H_{t-1}\right)M_H.
$$

Sau đó mới execute hedge rebalance để tạo $h_t$.

Không được dùng $h_t$ cho price move từ $t-1$ tới $t$.

---

## 17. Delta-Hedging Policies

### 17.1 Fixed threshold

Rebalance nếu:

$$
\left|\Delta_{\mathrm{account},t}\right|
>
\Delta_{\max}.
$$

Target có thể là:

$$
h_t^{*}
=
-\frac{\Delta_{\mathrm{option},t}}{\Delta_{\mathrm{hedgeInstrument},t}}.
$$

Với linear spot/perp hedge, denominator thường gần $1$ trong base-unit convention, nhưng vẫn phải đi qua contract multiplier và account-currency conversion.

### 17.2 Hysteresis band

Để tránh churn:

- trigger ở `outer_band`;
- hedge về `inner_target` thay vì luôn về zero.

Ví dụ:

$$
|\Delta|>0.10
\quad\Rightarrow\quad
\Delta_{\mathrm{target}}=\operatorname{sign}(\Delta)\times 0.02.
$$

### 17.3 Time-based

- mỗi $N$ phút;
- mỗi bar;
- trước/ sau funding timestamp;
- trước expiry risk window;
- cuối session.

### 17.4 Volatility-scaled band

Một heuristic có unit rõ ràng:

$$
\Delta_{\max,t}
=
\alpha
+
\beta\,|\Gamma_t|S_t\widehat{\sigma}_t\sqrt{\Delta t}.
$$

Nó phải được calibration và giới hạn min/max.

### 17.5 Whalley-Wilmott

Không nên hard-code công thức cũ:

$$
\left(
\frac{3}{2}
\frac{e^{\mu t}\Gamma\,\mathrm{Fee}}{\lambda}
\right)^{1/3}
$$

vì công thức này thiếu định nghĩa utility, transaction-cost unit, volatility scaling và mapping từ no-transaction region sang delta band. Các phiên bản Whalley-Wilmott phụ thuộc bài toán stochastic control cụ thể và có dimensional assumptions khác nhau.

Thiết kế đúng:

```python
class HedgeBandPolicy(Protocol):
    def band(self, state: OptionRiskState) -> HedgeBand:
        ...
```

Implement baseline trước:

- fixed threshold;
- hysteresis;
- time-based;
- realized-vol scaled.

`WhalleyWilmottPolicy` chỉ thêm sau khi:

1. ghi rõ objective/utility;
2. ghi rõ proportional transaction cost;
3. unit-test dimension;
4. reproduce numerical benchmark từ paper;
5. compare out-of-sample với simple bands.

---

## 18. Fees: Venue-Specific, Per-Leg, Versioned

### 18.1 Interface

```python
class OptionFeeModel(Protocol):
    def trading_fee(self, fill: OptionFillContext) -> Money:
        ...

    def delivery_fee(self, event: DeliveryContext) -> Money:
        ...
```

### 18.2 Deribit inverse BTC/ETH option fee

Theo fee schedule hiện hành tại thời điểm tài liệu được kiểm tra, inverse option fee có dạng:

$$
\mathrm{Fee}_{\mathrm{inverse}}
=
\min\left(
0.0003\;\mathrm{BaseCurrency},
0.125\times P_{\mathrm{option,base}}
\right)
\times |Q|.
$$

Ví dụ BTC option: hai nhánh đều mang unit BTC. Không nhân `0.0003 × spot_price` trong base-currency ledger.

### 18.3 Deribit linear USDC option fee

$$
\mathrm{Fee}_{\mathrm{linear}}
=
\min\left(
0.0003\,S_{\mathrm{index}},
0.125\,P_{\mathrm{option,USDC}}
\right)
\times |Q|\times M.
$$

### 18.4 Fee cap phải áp dụng per leg

Với straddle gồm call và put:

$$
\mathrm{Fee}_{\mathrm{package}}
=
\mathrm{Fee}_{\mathrm{call}}
+
\mathrm{Fee}_{\mathrm{put}},
$$

không phải apply cap lên tổng premium straddle như một option duy nhất.

### 18.5 Không hard-code mãi mãi

Fee schedule có thể thay đổi. `convention_version` và `fee_schedule_id` phải là một phần của run manifest. Historical backtest phải dùng fee schedule đúng thời kỳ nếu dữ liệu cho phép.

---

## 19. Lifecycle Và Settlement

### 19.1 Generic lifecycle events

```python
class OptionLifecycleEventType(str, Enum):
    LISTED = "listed"
    HALTED = "halted"
    RESUMED = "resumed"
    EXPIRED_OTM = "expired_otm"
    AUTO_EXERCISED = "auto_exercised"
    FUTURE_CREATED = "future_created"
    FUTURE_NETTED = "future_netted"
    CASH_DELIVERED = "cash_delivered"
    DELIVERY_FEE = "delivery_fee"
    ROLLED = "rolled"
```

### 19.2 Deribit inverse

- European style;
- automatic exercise at expiry;
- settlement in BTC/ETH;
- delivery price based on the venue-defined 30-minute TWAP window before 08:00 UTC;
- inverse intrinsic divided by delivery price.

### 19.3 Deribit linear USDC

Từ thay đổi settlement năm 2026, ITM linear options có thể được represented trong transaction log như:

1. option physically settles into matching expiry future at strike;
2. expiry future immediately cash settles into USDC;
3. economically equivalent cash P&L;
4. pre-existing expiry future position có thể net với generated future position.

Native engine nên support cả hai representation:

```text
settlement_representation = "economic_cash"
settlement_representation = "future_then_cash"
```

Kết quả economic P&L phải giống nhau; audit events có thể khác.

### 19.4 Expiry payoff linear

$$
\mathrm{CallPayoff}
=
M\max(S_T-K,0),
$$

$$
\mathrm{PutPayoff}
=
M\max(K-S_T,0).
$$

### 19.5 Pin risk

Với European cash-settled crypto options, pin risk không giống physical equity options nhưng vẫn có:

- jump trong delta/mark gần strike;
- delivery-price TWAP basis risk;
- hedge slippage trong 30-minute settlement window;
- venue delta-decay/risk-control behavior gần expiry;
- uncertain final moneyness khi spot oscillates quanh strike.

Engine nên mô hình hóa pin/settlement risk bằng explicit settlement window và hedge policy, không bằng random binary switch tùy ý.

---

## 20. Margin Architecture

### 20.1 Margin interface

```python
class OptionMarginModel(Protocol):
    def initial_margin(self, state: PortfolioState) -> MarginReport:
        ...

    def maintenance_margin(self, state: PortfolioState) -> MarginReport:
        ...

    def order_margin(self, state: PortfolioState, package: OptionPackageIntent) -> MarginReport:
        ...
```

### 20.2 Các implementation nên có

1. `LongPremiumOnlyMargin`
2. `VenueStandardMargin`
3. `ScenarioPortfolioMargin`
4. `ExternalVenueMarginValidator`
5. `NoMarginResearchModel`

### 20.3 Scenario PM native

Native scenario engine có thể shock:

$$
S^{(j)}=S(1+s_j),
$$

$$
\sigma^{(j,k)}
=
\max(\sigma+v_k,\sigma_{\min}),
$$

rồi revalue toàn bộ portfolio:

$$
L_{j,k}
=
V_0-V_{j,k}.
$$

Một approximation đơn giản:

$$
\mathrm{PM}
=
\max_{j,k} L_{j,k}
+
\mathrm{LiquidityAddon}
+
\mathrm{ConcentrationAddon}
+
\mathrm{ShortOptionFloor}.
$$

Nhưng report phải ghi rõ:

```text
margin_model = "scenario_approximation"
venue_exact = false
```

### 20.4 Không mô tả Deribit PM là 21 scenarios cố định

Mô hình Deribit hiện hành mô tả main table với underlying price buckets từ `-4` đến `+4`, volatility scenarios up/same/down, extended price shocks cho far-OTM short options và nhiều thành phần bổ sung. Parameters còn phụ thuộc currency pair, settlement group và account margin model. Vì vậy:

- không hard-code `[-15%, ..., +15%] × [-15%, 0, +15%]` như exact venue PM;
- không hard-code SOM bằng một công thức duy nhất cho mọi product;
- version hóa scenario set;
- dùng official `simulate_portfolio` hoặc account API để parity-test representative portfolios.

### 20.5 Margin liquidation sequence

1. mark portfolio;
2. compute maintenance margin;
3. convert collateral theo haircut/FX;
4. compare liquidation equity và MM;
5. nếu breach, generate liquidation orders theo policy;
6. execute ở adverse bid/ask + liquidation fee;
7. iterate cho tới khi safe hoặc account exhausted;
8. ghi liquidation audit trail.

---

## 21. P&L Attribution

### 21.1 Actual P&L và attribution phải tách nhau

Actual P&L đến từ ledger/equity. Greek attribution chỉ giải thích đường đi của P&L.

### 21.2 Second-order Taylor attribution

Với Greeks tại đầu interval:

$$
\Delta V
\approx
\Delta\,\Delta S
+
\frac{1}{2}\Gamma(\Delta S)^2
+
\Theta\,\Delta t
+
\mathrm{Vega}_{\mathrm{abs}}\,\Delta\sigma
+
\mathrm{Vanna}\,\Delta S\,\Delta\sigma
+
\frac{1}{2}\mathrm{Volga}(\Delta\sigma)^2
+
\varepsilon.
$$

Trong đó:

- $\Delta t$ theo năm nếu theta là annualized;
- $\Delta\sigma$ ở decimal;
- mọi term phải được conversion về cùng reporting currency;
- $\varepsilon$ chứa higher-order terms, surface movement, rate/forward changes, discrete hedge, spread, fee và model mismatch.

### 21.3 Portfolio aggregation

Với Greek $G_i$ đã normalized về reporting currency:

$$
G_{\mathrm{portfolio}}
=
\sum_i q_i M_i G_i.
$$

Không aggregate Greeks khác currency mà chưa conversion.

### 21.4 Gamma-scalping theoretical identity

Trong một Black-Scholes-style approximation, option được delta-hedged liên tục và bỏ qua costs:

$$
\mathrm{d}\Pi
\approx
\frac{1}{2}\Gamma S^2
\left(
\sigma_{\mathrm{real}}^2
-
\sigma_{\mathrm{imp}}^2
\right)\mathrm{d}t.
$$

Đây là lý thuyết để hiểu edge, không phải actual backtest formula. Actual backtest phải dùng observed option marks/fills, observed hedge path, fees, slippage và lifecycle cashflows.

---

## 22. Công Thức Strategy Và Arbitrage Đã Hiệu Chỉnh

### 22.1 Generic side-aware leg P&L

Đối với một leg linear trước expiry:

$$
\mathrm{PnL}_{i,t}
=
q_i M_i
\left(V_{i,t}-V_{i,0}\right)
-
\mathrm{Fees}_{i,t}.
$$

Khi đóng vị thế:

- long leg close ở bid;
- short leg close ở ask;
- entry long ở ask;
- entry short ở bid.

Mọi bảng strategy-specific nên derive từ generic formula này thay vì viết dấu cộng/trừ thủ công dễ sai.

### 22.2 Linear put-call parity theo forward

$$
C-P
=
D(F-K).
$$

Nếu dùng spot với continuous carry/dividend yield $q$:

$$
C-P
=
Se^{-q\tau}-Ke^{-r\tau}.
$$

Parity signal phải trừ:

- bid/ask crossing;
- trading fees;
- borrow/funding;
- collateral opportunity cost;
- margin cost;
- execution latency;
- settlement basis.

### 22.3 Box spread

Cho European linear options cùng expiry, settlement, multiplier và strike $K_1<K_2$:

- long call $K_1$;
- short call $K_2$;
- long put $K_2$;
- short put $K_1$.

Expiry payoff theo quote currency:

$$
\mathrm{Payoff}_{\mathrm{box}}
=
K_2-K_1.
$$

Fair present value:

$$
\mathrm{PV}_{\mathrm{box}}
=
D(K_2-K_1).
$$

Caveats:

- chỉ là pure financing trong cùng quote currency nếu settlement/multiplier/parity hoàn toàn nhất quán;
- inverse option box có payoff base currency biến thiên theo $S_T$;
- entry premium, collateral và accounting currency làm arbitrage phức tạp hơn;
- short legs có margin và execution risk;
- không giả định atomic fills nếu venue không có combo/block execution.

### 22.4 Risk reversal

Long 25-delta call và short 25-delta put thể hiện long skew/directional exposure. Skew quote:

$$
\mathrm{RR}_{25}
=
\sigma_{25\Delta,C}
-
\sigma_{25\Delta,P}.
$$

Nếu mục tiêu là pure skew:

- hedge delta;
- normalize vega;
- define forward-delta convention;
- match expiry;
- account for smile dynamics.

### 22.5 Dispersion

Index variance identity:

$$
\sigma_I^2
=
\sum_i w_i^2\sigma_i^2
+
2\sum_{i<j}w_iw_j\sigma_i\sigma_j\rho_{ij}.
$$

Classical dispersion cần index options và component options thực sự tương ứng với cùng basket. Với crypto, “BTC index vs altcoin options” thường là cross-asset relative-value trade, không phải classical index dispersion. Engine nên đặt tên đúng để tránh false hedge assumptions.

### 22.6 Variance replication

Continuous approximation:

$$
K_{\mathrm{var}}
=
\frac{2e^{rT}}{T}
\left[
\int_0^F \frac{P(K)}{K^2}\,\mathrm{d}K
+
\int_F^\infty \frac{C(K)}{K^2}\,\mathrm{d}K
\right].
$$

Discrete VIX-style approximation:

$$
\sigma^2
=
\frac{2}{T}
\sum_i
\frac{\Delta K_i}{K_i^2}
e^{rT}Q(K_i)
-
\frac{1}{T}
\left(
\frac{F}{K_0}-1
\right)^2.
$$


Lưu ý: một static option strip không tự động loại bỏ mọi delta/forward exposure trong implementation thực tế. Model-free variance replication có assumptions về continuum strikes, forward term và dynamic trading. Backtest phải mô hình hóa discrete strikes, missing tails, bid/ask, rebalance và expiry.

### 22.7 Max pain và dealer gamma

Max pain statistic:

$$
\mathrm{Pain}(S)
=
\sum_{i\in C} \mathrm{OI}_i\max(S-K_i,0)
+
\sum_{j\in P} \mathrm{OI}_j\max(K_j-S,0).
$$

Tuy nhiên:

- OI không cho biết dealer đang long hay short;
- không biết customer/dealer side từ aggregate OI;
- không biết hedge ratio thực tế;
- không biết OTC positions;
- không biết position đã được net qua expiry khác hay venue khác.

Do đó `NetDealerGamma` từ OI cần được gắn label `model_assumption`, không phải observed fact. Gamma-squeeze/max-pain nên nằm trong signal analytics/template, không nằm trong core pricing hay arbitrage guarantee.

---

## 23. Strategy Templates Engine Nên Hỗ Trợ

Engine không cần một class riêng cho từng strategy. Một execution/ledger/lifecycle engine generic có thể support mọi strategy thông qua package builders.

| Nhóm | Template | Legs / hedge | Data bắt buộc | Domain caveat |
|---|---|---|---|---|
| Volatility | Long straddle | Long ATM C + P | two-sided chain, IV, underlying | vega/gamma long, theta negative |
| Volatility | Short straddle | Short ATM C + P | margin, liquidation, depth | tail risk rất lớn |
| Volatility | Strangle | OTM C + P | delta selector | strike skew quan trọng |
| Volatility | Gamma scalping | Long convexity + dynamic hedge | intraday underlying + option quotes | hedge timing quyết định kết quả |
| Volatility | IV-RV / VRP | long/short vol package + hedge | forecast RV, IV surface | phải avoid event leakage |
| Term structure | Calendar | short/long different expiry | aligned term surface | near-expiry lifecycle |
| Term structure | Diagonal | different strike + expiry | surface + directional model | mixed delta/vega/theta |
| Directional | Bull call spread | long low-K C, short high-K C | bid/ask | defined max profit/loss |
| Directional | Bear put spread | long high-K P, short low-K P | bid/ask | defined risk |
| Directional | Ratio spread | unequal ratios | depth and margin | naked tail on short-heavy side |
| Convexity | Ratio backspread | short near strike, long more wings | skew and package liquidity | not always zero-cost |
| Range | Butterfly | 1:-2:1 or broken wing | strike grid | pin/expiry sensitivity |
| Range | Iron condor | four-leg credit | margin offset | execution atomicity |
| Skew | Risk reversal | long one wing, short other | delta convention | directional unless hedged |
| Skew | Fly / butterfly quote | wing-center-wing | surface | compare in vega-normalized units |
| Overlay | Covered call | long underlying + short call | underlying inventory | downside remains mostly unhedged |
| Overlay | Cash-secured put | cash + short put | cash/margin | equivalent equity entry profile |
| Overlay | Protective put | long underlying + long put | underlying inventory | insurance premium drag |
| Overlay | Collar | underlying + long put + short call | three-leg/underlying package | capped upside/downside |
| Overlay | Tail hedge ladder | multiple OTM puts | long history, roll rules | bleed and gap liquidity |
| Arbitrage | Synthetic forward | long C + short P | parity, borrow/funding | convention-specific |
| Arbitrage | Conversion/reversal | spot + C/P package | borrow, fees, margin | not risk-free after frictions |
| Arbitrage | Box spread | four legs | same expiry/settlement | linear/inverse distinction |
| Relative value | Cross-venue vol | long cheap, short rich + hedge | synchronized venues | latency, collateral split |
| Relative value | Dispersion | index vs components | matched option universe | classical vs cross-asset distinction |
| Variance | Variance strip | broad OTM strip | dense strikes | tail extrapolation |
| Event | Earnings/event vol | pre/post event package | event calendar | avoid using event outcome |
| Flow analytics | Max pain/gamma wall | underlying or option package | OI/flow assumptions | OI does not reveal dealer sign |

### 23.1 Template interface

```python
class OptionPackageBuilder(Protocol):
    def build(
        self,
        snapshot: OptionChainSnapshot,
        portfolio: OptionPortfolioView,
        signal: float,
    ) -> tuple[OptionPackageIntent, ...]:
        ...
```

Strategy code vẫn có thể sống bên ngoài QuantBT. Package chỉ cung cấp reusable builders cho common structures.

---

## 24. Corrected Gamma-Scalping Implementation Pattern

### 24.1 Không viết P&L trực tiếp trong strategy

Strategy chỉ làm ba việc:

1. chọn option package;
2. xác định entry/exit/roll;
3. phát hedge target hoặc hedge policy.

Backend chịu trách nhiệm fill, cash, P&L, fee, margin và settlement.

### 24.2 Skeleton

```python
class GammaScalpingTemplate:
    def __init__(self, config: GammaScalpingConfig):
        self.config = config

    def on_snapshot(self, ctx: OptionStrategyContext) -> list[OptionPackageIntent]:
        intents: list[OptionPackageIntent] = []

        if not ctx.has_active_package("gamma_scalp"):
            selected = ctx.selector.select_straddle(
                target_dte_days=self.config.target_dte_days,
                max_spread_bps=self.config.max_spread_bps,
                min_open_interest=self.config.min_open_interest,
            )
            if selected is not None and self.entry_filter(ctx, selected):
                intents.append(self.build_long_straddle(ctx, selected))
                return intents

        if self.should_roll_or_exit(ctx):
            intents.extend(ctx.close_package("gamma_scalp"))
            return intents

        # Hedge execution is delegated to the configured HedgePolicy.
        return intents
```

### 24.3 Backend pseudo-loop

```python
for event in option_event_tape:
    state.advance_to(event.timestamp_ns)
    state.market.apply(event)
    state.process_pending_orders()
    state.lifecycle.process_due_events()
    state.carry.accrue()

    pre_trade = state.snapshot_risk_and_equity()
    packages = strategy.on_snapshot(pre_trade.strategy_context)

    for package in packages:
        executor.execute_package(package, state)

    hedge_order = hedge_policy.create_order(state.risk_view())
    if hedge_order is not None:
        executor.execute_order(hedge_order, state)

    state.margin.evaluate_and_liquidate_if_needed()
    state.record_audit_row()
```

### 24.4 Exit và roll

Các rule nên configurable:

- `dte_exit_days`;
- `take_profit_pct_of_debit`;
- `stop_loss_pct_of_debit`;
- `iv_edge_exit`;
- `max_gamma_notional`;
- `max_vega_notional`;
- `max_hedge_turnover`;
- `force_flat_before_settlement_window`;
- `roll_to_target_dte`.

Không nên mặc định luôn giữ tới `DTE <= 2` vì daily/weekly crypto options và settlement window có đặc thù khác nhau.

---

## 25. Result Contract

### 25.1 Giữ tương thích `BacktestResultV2`

```python
@dataclass
class OptionBacktestResult(BacktestResultV2):
    cash_balances: pd.DataFrame = field(default_factory=pd.DataFrame)
    option_marks: pd.DataFrame = field(default_factory=pd.DataFrame)
    greeks: pd.DataFrame = field(default_factory=pd.DataFrame)
    pnl_attribution: pd.DataFrame = field(default_factory=pd.DataFrame)
    settlements: pd.DataFrame = field(default_factory=pd.DataFrame)
    package_report: pd.DataFrame = field(default_factory=pd.DataFrame)
    risk_report: pd.DataFrame = field(default_factory=pd.DataFrame)
```

### 25.2 `positions` và `closes`

- `positions`: quantity matrix của option + hedge instruments;
- `closes`: mark price matrix theo native quote units;
- currency/multiplier/convention nằm trong metadata hoặc instrument registry;
- `equity`: reporting currency;
- `fees`: reporting currency aggregate;
- raw per-currency fees nằm trong diagnostics/ledger report.

### 25.3 Artifacts bắt buộc

```text
orders_report.csv
fills_report.csv
packages_report.csv
positions_report.csv
cash_balances.csv
option_marks.csv
greeks.csv
pnl_attribution.csv
margin_report.csv
settlements.csv
liquidations.csv
equity_curve.csv
returns.csv
metrics_summary.json
run_manifest.json
instrument_registry.json
venue_conventions.json
config.json
```

---

## 26. NautilusTrader Validation

Nautilus hiện có first-class option types gồm `OptionContract`, `OptionSpread`, `CryptoOption` và `CryptoOptionSpread`. Với Deribit/OKX/Bybit-style crypto options, `CryptoOption` phù hợp hơn một generic `OptionContract` hard-code.

### 26.1 Không viết constructor adapter quá sớm

Nautilus instrument constructors và adapter capabilities thay đổi theo version. Không nên đưa một constructor hard-coded vào core guide rồi coi là ổn định. Cần:

- pin Nautilus version trong optional dependency;
- map theo official `CryptoOption` fields của version đó;
- thêm adapter compatibility tests;
- fail rõ ràng nếu version mismatch;
- không import Nautilus khi user chỉ chạy native engine.

### 26.2 Validation scope ban đầu

Phase đầu chỉ cần validate:

1. one linear option round trip;
2. one inverse option if adapter supports exact convention;
3. two-leg spread;
4. option + perpetual delta hedge;
5. expiry settlement;
6. fee and account reports;
7. order/fill timestamps;
8. position quantities;
9. equity parity.

### 26.3 Parity tolerance

Không nên đặt mục tiêu chung “P&L sai số < 0.01%” cho mọi run. Tolerance phải theo component:

```text
quantity_diff           = 0
fill_timestamp_diff     = expected by policy
fill_price_diff         <= tick/slippage tolerance
fee_diff                <= 1 fee currency unit precision
settlement_diff         <= venue rounding tolerance
final_equity_diff       <= explicit absolute + relative tolerance
```

Nếu mark policy khác nhau, final mark equity có thể khác nhưng realized cashflows vẫn parity.

---

## 27. Performance Design

### 27.1 Cold path và hot path

Cold path:

- dataclass validation;
- Pandas normalization;
- instrument registry;
- package construction;
- diagnostics.

Hot path:

- contiguous arrays;
- integer instrument codes;
- row pointers;
- numeric enum codes;
- preallocated state arrays;
- Numba kernels;
- no dict/list append trong inner loop.

### 27.2 Preallocated buffers

```python
positions = np.zeros(n_instruments, dtype=np.float64)
avg_price = np.zeros(n_instruments, dtype=np.float64)
cash = np.zeros(n_currencies, dtype=np.float64)
greeks = np.zeros((n_steps, n_greeks), dtype=np.float64)
equity = np.zeros(n_steps, dtype=np.float64)
fees = np.zeros(n_steps, dtype=np.float64)
```

### 27.3 Instrument lookup

- map symbol string → integer code một lần;
- metadata arrays theo code;
- selection trong snapshot dùng sorted expiry/strike indices;
- cache nearest-delta candidates;
- không gọi Pandas `.loc` trong event loop.

### 27.4 Hai mức fidelity

```text
research_fast:
    mark/mid, no queue, approximate margin, vectorized selectors

event_exact:
    bid/ask/depth, package policy, multi-currency ledger,
    margin, lifecycle, settlement, audit logs
```

Benchmark phải report fidelity mode, không so runtime mà bỏ qua khác biệt semantics.

---

## 28. Testing Plan

### 28.1 Pricing tests

- Black-76 call/put parity;
- inverse parity;
- intrinsic limits khi $\tau \rightarrow 0$;
- finite-difference delta/gamma/vega;
- monotonicity theo $F$, $K$, $\sigma$;
- linear/inverse currency conversion;
- deep ITM/OTM numerical stability;
- zero/near-zero volatility.

### 28.2 IV tests

- recover known volatility từ generated prices;
- reject below intrinsic;
- reject above upper bound;
- bid IV ≤ ask IV khi quotes hợp lệ;
- deterministic convergence;
- tail/high-vol cases.

### 28.3 Execution tests

- long fills ask, short fills bid;
- AON rollback;
- IOC partial;
- FOK reject;
- stale quote reject;
- quantity step rounding;
- min quantity/notional;
- maker vs taker fee;
- package debit/credit guard;
- sequential leg risk;
- hedge-after-primary failure.

### 28.4 Ledger tests

- long premium paid immediately;
- short premium received immediately;
- round trip with no price move equals negative fees/spread;
- inverse premium BTC and reporting USD equity;
- hedge unrealized P&L included every event;
- no double counting realized hedge P&L;
- settlement closes position exactly once;
- fee currency conversion;
- equity identity every step.

### 28.5 Lifecycle tests

- OTM expires zero;
- ITM linear payoff;
- ITM inverse payoff;
- delivery price TWAP supplied only after window close;
- auto exercise;
- future-then-cash representation;
- pre-existing expiry future netting;
- roll closes old and opens new without overlap bug.

### 28.6 Surface tests

- total variance non-negative;
- no obvious calendar inversion;
- wing extrapolation;
- calibration reproducibility;
- no use of future expiry data in historical snapshot calibration.

### 28.7 Strategy golden tests

Mỗi structure cần payoff grid tại expiry:

- long/short call/put;
- straddle/strangle;
- vertical;
- butterfly;
- condor;
- calendar before near expiry;
- risk reversal;
- ratio backspread;
- box;
- covered call;
- collar.

### 28.8 Integration tests

- endpoint → engine → result helpers;
- report export;
- current non-option tests unchanged;
- import QuantBT không cần Nautilus;
- option engine disabled gracefully nếu dependency optional thiếu;
- representative Deribit fee examples;
- official margin simulation parity samples.

---

## 29. File-by-File Implementation Guide Cho Agent

### Phase 0 — Baseline protection

1. Run toàn bộ existing tests.
2. Snapshot endpoint support matrices.
3. Snapshot benchmark outputs.
4. Không sửa behavior của existing backends.
5. Tạo feature branch riêng.

Acceptance:

```text
all existing tests pass
no public endpoint regression
no import-time Nautilus dependency
```

### Phase 1 — Domain schema

Files:

```text
core/schema.py
options/schema.py
options/conventions.py
options/data.py
```

Tasks:

- add `AssetType.OPTION`;
- implement `OptionInstrumentSpec`;
- implement premium/settlement/exercise enums;
- implement instrument registry;
- implement Deribit inverse and linear convention configs;
- implement Binance convention config without hard-coded unsupported assumptions;
- add schema tests.

### Phase 2 — Pricing, IV and Greeks

Files:

```text
options/pricing.py
options/iv.py
options/greeks.py
options/surface.py
```

Tasks:

- linear Black-76;
- inverse pricing;
- intrinsic payoff;
- normalized Greek units;
- robust IV solver;
- finite-difference test harness;
- raw SVI with no-arb diagnostics;
- do not integrate execution yet.

### Phase 3 — Data tape and selectors

Files:

```text
options/tape.py
options/selectors.py
```

Tasks:

- normalize long-form chain;
- compile CSR/ragged tape;
- snapshot lookup;
- stale quote guard;
- ATM/delta/DTE/moneyness/liquidity selectors;
- no-lookahead tests.

### Phase 4 — Package compiler and execution

Files:

```text
options/packages.py
options/execution.py
```

Tasks:

- package/leg intents;
- compile to existing `OrderIntent` leaf orders;
- AON/BEST_EFFORT/SEQUENTIAL/HEDGE_AFTER_PRIMARY;
- bid/ask/depth fill models;
- package rollback;
- diagnostics.

### Phase 5 — Ledger and lifecycle

Files:

```text
options/ledger.py
options/lifecycle.py
options/fees.py
```

Tasks:

- multi-currency cash ledger;
- position average price;
- realized/unrealized accounting;
- mark/liquidation equity;
- inverse/linear fee models;
- expiry and settlement;
- audit invariants.

### Phase 6 — Hedge and margin

Files:

```text
options/hedging.py
options/margin.py
```

Tasks:

- fixed/hysteresis/time-based hedge;
- account-currency delta;
- standard margin;
- scenario PM approximation;
- margin rejection/liquidation;
- external venue validation interface.

### Phase 7 — Backend, engine and endpoint

Files:

```text
backends/native_option.py
engines.py
endpoint.py
core/results.py
metrics/options_analytics.py
```

Tasks:

- implement `NativeOptionBackend`;
- implement `OptionBacktestEngine`;
- implement `QuantBTEndpoint.options(...)`;
- return `OptionBacktestResult` compatible with V2;
- update support matrix;
- export reports.

### Phase 8 — Strategy templates

Files:

```text
options/templates/*.py
examples/options/*.py
```

Tasks:

- package builders only;
- no duplicate accounting logic;
- no direct Pandas loop P&L;
- implement common structures;
- add golden payoff tests.

### Phase 9 — Nautilus validation

Files:

```text
adapters/nautilus/options.py
tests/options/test_nautilus_options.py
```

Tasks:

- pin Nautilus version;
- map to `CryptoOption`/`CryptoOptionSpread` where appropriate;
- validate representative runs;
- export parity report;
- keep optional dependency boundary.

### Phase 10 — Performance and production hardening

- compile prepared tapes once;
- cache instrument registry;
- benchmark bars/quotes/packages/fills per second;
- memory profile;
- fuzz invalid data;
- deterministic replay with random seed;
- run manifest with data hash, convention version and engine version.

---

## 30. Recommended Configuration Objects

```python
@dataclass(frozen=True)
class NativeOptionConfig:
    account: AccountConfig
    reporting_currency: str = "USD"
    simulation_mode: str = "event"
    mark_policy: str = "venue_mark"
    liquidation_mark_policy: str = "bid_ask"
    decision_fill_policy: str = "next_snapshot"
    max_quote_age_ns: int = 5_000_000_000
    allow_model_mark_fallback: bool = False
    reject_crossed_quotes: bool = True
    use_depth: bool = True
    margin_model_id: str = "scenario_approximation_v1"
    fee_schedule_id: str = "venue_historical"
    deterministic_seed: int = 42


@dataclass(frozen=True)
class GammaScalpingConfig:
    target_dte_days: float = 30.0
    dte_tolerance_days: float = 5.0
    max_spread_bps: float = 500.0
    min_open_interest: float = 0.0
    package_qty: float = 1.0
    hedge_instrument_id: str = "BTCUSDT-PERP.BINANCE"
    hedge_policy: str = "hysteresis"
    outer_delta_band: float = 0.10
    inner_delta_target: float = 0.02
    minimum_hedge_interval_ns: int = 60_000_000_000
    dte_exit_days: float = 2.0
    force_flat_before_settlement_window: bool = True
```

---

## 31. Data Requirements Cho Historical Backtest Và Paper Trading

### 31.1 Historical minimum

- instrument definitions theo thời gian;
- option bid/ask hoặc order book;
- index price;
- forward/futures price dùng cho IV;
- mark price/mark IV nếu available;
- underlying hedge market bid/ask;
- trades hoặc depth nếu mô hình maker/impact;
- OI và volume cho selectors;
- settlement/delivery prices;
- fee schedule history;
- margin rule version;
- funding/borrow/cash yield cho hedge/carry;
- FX conversion giữa premium, settlement và reporting currencies.

### 31.2 Không nên backtest execution chỉ với end-of-day option chain

EOD chain có thể dùng cho:

- daily roll;
- slow VRP;
- surface research;
- expiry payoff study.

Nó không đủ cho:

- intraday gamma scalping;
- legging risk;
- quote-side fill;
- maker/taker;
- settlement-window hedge;
- cross-venue latency arbitrage.

### 31.3 Paper trading stream

Pipeline đề xuất:

```text
Venue WebSocket/REST
        │
        ▼
Normalizer
        │
        ├── instrument registry updates
        ├── option quote snapshots
        ├── underlying/index/forward
        └── settlement/lifecycle events
        │
        ▼
Append-only event store
        │
        ├── live strategy consumer
        └── exact replay into NativeOptionBackend
```

Cùng một normalized event schema phải phục vụ cả paper/live replay và historical backtest.

---

## 32. Smart Architecture Improvements Beyond The Initial Plan

### 32.1 Convention-first design

Pricing model không phải object trung tâm. `OptionInstrumentSpec + VenueConvention` mới là nguồn sự thật. Pricing chỉ là một service được chọn theo convention.

### 32.2 Ledger-first accounting

P&L không được quản lý trong strategy class. Strategy chỉ tạo intent; ledger quyết định cash/equity.

### 32.3 Package compiler pattern

Multi-leg strategy → package intent → leaf `OrderIntent`. Pattern này reuse được current QuantBT order/report infrastructure và giúp Nautilus validation dễ hơn.

### 32.4 Prepared tape cache

Giống `PreparedMarketArrays` và `CompiledOrderArrays` hiện tại, options cần:

```text
PreparedOptionTape
CompiledOptionPackages
InstrumentRegistrySignature
VenueConventionSignature
```

Engine phải reject prepared objects nếu timestamp layout, instrument registry hoặc convention version thay đổi.

### 32.5 Explicit fidelity manifest

Mỗi run phải lưu:

```json
{
  "quote_fidelity": "l1_bid_ask",
  "depth_fidelity": "top_of_book_only",
  "maker_fill_model": "disabled",
  "margin_fidelity": "scenario_approximation",
  "settlement_fidelity": "official_delivery_price",
  "surface_fidelity": "observed_mark_iv",
  "decision_fill_policy": "next_snapshot"
}
```

Điều này quan trọng hơn một claim chung chung như “production-grade” hoặc “100% accurate”.

### 32.6 Separate observed Greeks and model Greeks

```text
venue_delta
venue_gamma
venue_vega
venue_theta
model_delta
model_gamma
model_vega
model_theta
```

Không overwrite một loại bằng loại còn lại. Differences chính là useful diagnostics.

### 32.7 Separate risk currency

Greek report nên có:

```text
native_currency
settlement_currency
reporting_currency
```

Đặc biệt quan trọng với inverse options.

---

## 33. Những Claim Không Nên Dùng Trong Tài Liệu Production

Không nên dùng các câu sau nếu chưa có benchmark/audit tương ứng:

- “hàng triệu contract/giây”;
- “chuẩn xác 100% với bot thực tế”;
- “Deribit PM giống SPAN/TIMS”;
- “atomic all-or-none” nếu venue không có combo/block support;
- “pure risk-free arbitrage” trước fees, margin, borrow và settlement basis;
- “variance swap không cần dynamic hedge”;
- “dealer gamma được suy ra từ OI”;
- “Nautilus mapping hoàn chỉnh” khi adapter version chưa pin;
- “P&L parity < 0.01%” không có component-specific tolerance.

Thay bằng các label có thể audit:

```text
execution_fidelity = ...
margin_fidelity = ...
pricing_convention = ...
validation_status = ...
known_limitations = ...
```

---

## 34. Acceptance Criteria Cho Phiên Bản V1

V1 được coi là hoàn thành khi:

1. Existing QuantBT test suite không regression.
2. `QuantBTEndpoint.options(...)` chạy được.
3. Linear và inverse option instrument được phân biệt đúng.
4. Bid/ask fill và per-leg fee đúng unit.
5. Premium cashflow không double-count.
6. Underlying hedge dùng previous position cho prior price move.
7. Multi-currency equity reconciliation pass mỗi event.
8. Expiry settlement linear và inverse pass golden tests.
9. AON package rollback atomic trong simulation state.
10. Long/short call, put, straddle, vertical, butterfly, condor, calendar và covered call pass payoff tests.
11. Greeks finite-difference error nằm trong tolerance.
12. IV solver recover known volatility.
13. Result trả `BacktestResultV2`-compatible artifacts.
14. Run manifest chứa convention, fee, margin và data hashes.
15. Có ít nhất một Deribit inverse gamma-scalping example và một linear spread example.
16. Có parity samples với official venue calculations hoặc Nautilus cho phần được hỗ trợ.

---

## 35. Roadmap Ưu Tiên

### Milestone 1 — Correctness core

- schema/conventions;
- long-form chain + compiled tape;
- linear/inverse pricing;
- IV/Greeks;
- ledger;
- basic market fills;
- expiry settlement.

### Milestone 2 — Package execution

- AON;
- best effort;
- sequential;
- hedge after primary;
- vertical/straddle/calendar templates.

### Milestone 3 — Risk

- delta hedge policies;
- standard margin;
- scenario PM;
- liquidation;
- Greek limits.

### Milestone 4 — Analytics

- P&L attribution;
- surface/skew/term structure;
- VRP;
- package reports;
- strategy template library.

### Milestone 5 — External validation

- Deribit fee/settlement parity;
- official margin simulation parity;
- Nautilus option adapter;
- report bundle parity.

### Milestone 6 — Performance

- Numba event kernels;
- prepared tape cache;
- depth simulation;
- benchmark suite;
- large chain memory profiling.

---

## 36. Final Recommendation

Thiết kế ban đầu nên được giữ lại về **ý tưởng module hóa**, taxonomy strategy, multi-leg execution, lifecycle, margin, Greeks và Nautilus validation. Tuy nhiên, implementation cần xoay quanh năm trụ cột sau:

1. **Convention-first:** linear/inverse/quanto và settlement currency phải rõ trước khi pricing.
2. **Ragged event tape:** không dùng dense fixed-contract matrix làm canonical chain.
3. **Ledger-first:** cash, premium, fee, positions và settlement là nguồn P&L duy nhất.
4. **Specialized backend:** `native_option` đứng riêng, không patch generic OHLC event kernel.
5. **Package compiler + stable endpoint:** reuse `OrderIntent`, package enums, `BacktestResultV2` và QuantBT report ecosystem.

Nếu làm theo cấu trúc này, QuantBT Options Engine sẽ:

- phù hợp với codebase hiện tại;
- giảm số file phải sửa trong core;
- không phá các existing backends;
- support được cả directional, volatility, overlay và arbitrage strategies;
- đúng hơn với Deribit/Binance domain;
- dễ audit;
- dễ test;
- dễ tối ưu bằng Numba;
- dễ nối với paper/live event stream;
- dễ validation bằng Nautilus hoặc venue API sau này.

---

## 37. Nguồn Đối Chiếu

### QuantBT repository

- QuantBT README and architecture overview: <https://github.com/BobbyAxerol/quantbt>
- Core schema: <https://github.com/BobbyAxerol/quantbt/blob/main/core/schema.py>
- Arbitrage domain and `OptionsVolArbSpec`: <https://github.com/BobbyAxerol/quantbt/blob/main/core/arbitrage.py>
- Generic order/fill domain: <https://github.com/BobbyAxerol/quantbt/blob/main/core/orders.py>
- Native event backend: <https://github.com/BobbyAxerol/quantbt/blob/main/backends/native_event.py>
- Engine facade: <https://github.com/BobbyAxerol/quantbt/blob/main/engines.py>
- Public endpoint facade and support matrices: <https://github.com/BobbyAxerol/quantbt/blob/main/endpoint.py>
- Nautilus adapter: <https://github.com/BobbyAxerol/quantbt/tree/main/adapters/nautilus>

### Deribit official documentation

- Inverse options conventions and settlement: <https://support.deribit.com/hc/en-us/articles/31424939096093-Inverse-Options>
- Linear USDC options and 2026 settlement flow: <https://support.deribit.com/hc/en-us/articles/31424932728093-Linear-USDC-Options>
- Fees and option fee caps: <https://support.deribit.com/hc/en-us/articles/25944746248989-Fees>
- Portfolio Margin: <https://support.deribit.com/hc/en-us/articles/25944756247837-Portfolio-Margin>
- Settlement and delivery price: <https://support.deribit.com/hc/en-us/articles/29734325712413-Settlement>
- Instrument metadata API: <https://docs.deribit.com/api-reference/market-data/public-get_instruments>
- Portfolio simulation API: <https://docs.deribit.com/api-reference/upcoming/account-management/private-simulate_portfolio>

### Binance official documentation

- Binance European Options contract specifications: <https://www.binance.com/en/support/faq/detail/cdee5d43b70d4d2386980d41786a8533>
- Binance Options listing rules: <https://www.binance.com/en/support/faq/detail/28b922eef0ce41189583dc184cdbd48f>
- Binance Options API overview: <https://www.binance.com/en/support/faq/detail/fe0be251ac014a8082e702f83d089e54>

### Pricing, surface, and variance references

- Fischer Black, *The Pricing of Commodity Contracts* (1976): <https://www.sciencedirect.com/science/article/abs/pii/0304405X76900246>
- Gatheral and Jacquier, *Arbitrage-free SVI volatility surfaces*: <https://arxiv.org/abs/1204.0646>
- Cboe Volatility Index Mathematics Methodology: <https://cdn.cboe.com/resources/indices/Cboe_Volatility_Index_Mathematics_Methodology.pdf>
- Whalley and Wilmott, *An Asymptotic Analysis of an Optimal Hedging Model for Option Pricing with Transaction Costs*: <https://users.ox.ac.uk/~ofrcinfo/file_links/mf_papers/1999mf08.pdf>

### NautilusTrader official documentation

- Options concepts and instrument types: <https://nautilustrader.io/docs/latest/concepts/options/>
- Instrument taxonomy: <https://nautilustrader.io/docs/latest/concepts/instruments/>

---

## Appendix A — Minimal Formula Unit Conventions

| Quantity | Internal unit |
|---|---|
| Price linear option | quote currency per underlying unit |
| Price inverse option | base currency per underlying unit |
| Quantity | contracts |
| Multiplier | underlying units per contract |
| Volatility | decimal, e.g. `0.60` |
| Time | ACT/365 years |
| Delta | selected risk currency per one unit underlying move |
| Gamma | selected risk currency per squared underlying move |
| Vega | selected risk currency per `1.0` volatility change |
| Theta | selected risk currency per year of calendar time |
| Fee | native fee currency, then converted for reporting |
| Equity | reporting currency |

---

## Appendix B — Required Audit Invariants

```text
1. No position exists before its listing timestamp.
2. No quote after decision time is used for selection.
3. Buy does not fill below ask unless limit/maker/depth model explains it.
4. Sell does not fill above bid unless limit/maker/depth model explains it.
5. AON package either commits all fills or commits none.
6. Premium cashflow occurs exactly once per fill.
7. Fee occurs exactly once per fill/delivery.
8. Expiry settlement occurs exactly once.
9. Hedge P&L uses the position held before the price move.
10. Equity equals converted cash plus converted marked positions.
11. Realized + unrealized + carry + settlement - fees reconciles to equity change.
12. Native and reporting Greek units are never mixed silently.
13. Convention version is stored in every run manifest.
14. Missing/stale quotes generate diagnostics, not silent forward fill across long gaps.
15. Model price fallback is explicitly labeled and never treated as an executable quote.
```
