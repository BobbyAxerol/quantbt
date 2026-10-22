# QuantBT — Mode 5 Upgrade V1
## Diagnostics-first Robust Static Calibration · Kế thừa Spec V1.1 · Guide triển khai và kiểm chứng 12 phase

**Document ID:** `QUANTBT-MODE5-UPGRADE-V1`  
**Ngày biên soạn:** 08/10/2026  
**Trạng thái:** `APPROVED_DIRECTION / IMPLEMENTATION_AND_RESEARCH_GUIDE` — đây không phải chứng nhận implementation đã hoàn tất hoặc có lợi nhuận mới.  
**Tài liệu gốc:** `MODE5_INVARIANT_AND_ALPHA_PROFILING_SPEC_V1_1.md` trong `export_mode5_direction_a_bundle.zip`.  
**Nguồn alpha:** `alphas.zip`, gồm A-SC, A-HMA, A-VWAP và A-HASH cùng các helpers/reference.  
**Mục tiêu package:** kế thừa nền QuantBT 1.1.1 và nâng cấp Mode 4/sampler đã có tại checkout thực; version của guide không tự đổi version package.  
**Người thực hiện:** Claude/OpenCode hoặc agent được giao; người duyệt quyết định khoa học, phạm vi và promotion là maintainer.

> **Mệnh lệnh chính:** chạy diagnostics có thiết kế và evidence trước tuning Mode 5 chính thức. Diagnostics phải đo được cả chất lượng kinh tế, độ nhạy tham số, khác biệt giữa environments, transfer theo thời gian, execution risk và uncertainty. Sau đó mới chọn recipe, freeze calibration plan, tuning bằng QuantBT, và đánh giá với data role đúng.
>
> **Không đổi hướng A thành dự án khác.** Giữ tám chương, năm trục diagnostics, năm empirical batteries, ba họ objective và bốn selector slots của Spec V1.1. Sửa định nghĩa toán, phép thử và mức claim ở những chỗ chưa đúng; không bảo vệ một kết luận chỉ vì đã xuất hiện trong báo cáo cũ.

## Cách đọc và thứ tự hiệu lực

1. Quyết định người dùng trong guide này có hiệu lực cho đợt mở rộng Mode 5.
2. Contracts và evidence đã certify của QuantBT/Mode 4 được tái sử dụng; không suy ra code mới từ những line numbers lịch sử.
3. Spec V1.1 và Baseline/T1/T2 là nguồn nghiên cứu cần bảo toàn; phần errata trong Chương 3 thay cho những bảng/diễn giải mâu thuẫn, không viết đè artifacts.
4. Mọi tên API/module/config được đánh dấu **đề xuất** phải map vào source thật ở M5-01. Không viết script gọi một API tưởng tượng rồi coi là integration hoàn tất.
5. `.py`/CLI + Markdown/JSON/Parquet là workflow chính. Notebook có thể đọc evidence nhưng không là test harness, state store hay điều kiện tái hiện.

**Nguồn được đánh dấu:** `[D0–D5]` là file người dùng cung cấp, định danh trong Phụ lục A; `[S1–S14]` là tài liệu kỹ thuật primary trong Phụ lục F. Các công thức và protocols đề xuất dưới đây là specification để implement/test, không phải kết quả thị trường đã đo. Các tables T1/T2 là số liệu đọc lại từ JSON; chưa được tái tính từ equity/fills gốc trong lượt biên soạn này.

## Mục lục

- [Chương 1 — Triết lý và mục tiêu](#chapter-1)
- [Chương 2 — Kế thừa QuantBT và ranh giới architecture](#chapter-2)
- [Chương 3 — Evidence cũ, errata và alpha inventory](#chapter-3)
- [Chương 4 — Diagnostics cockpit và ma trận đo lường](#chapter-4)
- [Chương 5 — Toán học objectives và statistical contracts](#chapter-5)
- [Chương 6 — Bốn selectors và calibration lifecycle](#chapter-6)
- [Chương 7 — Implementation, schemas, tests và 12 phases](#chapter-7)
- [Chương 8 — Kết luận được phép và Definition of Done](#chapter-8)
- [Phụ lục A — Source identities](#appendix-a)
- [Phụ lục B — Mandatory test register](#appendix-b)
- [Phụ lục C — Mathematical oracle nhỏ đã chạy](#appendix-c)
- [Phụ lục D — Report templates và handoff](#appendix-d)
- [Phụ lục E — Mapping toàn bộ điều chỉnh vào Spec V1.1](#appendix-e)
- [Phụ lục F — Nguồn kỹ thuật](#appendix-f)

---

<a id="chapter-1"></a>
# Chương 1 — Executive summary và triết lý Direction A

## 1.1 Giữ diagnostics-first như một product contract

Luồng bắt buộc cho đường **Mode 5 Upgrade V1 opt-in**:

```text
Alpha + parameter schema + economic/data contracts
    → technical admission
    → registered diagnostic study
    → executed candidate/environment/probe matrices
    → five-axis profile + five empirical batteries
    → evidence-backed advisory dossier
    → frozen CalibrationPlan
    → Mode 5 tuning with the approved recipe
    → selected-configuration audit / independent evaluation where available
    → calibration result + explicitly scoped validation evidence
```

Không đảo thành tune trước rồi chỉ làm diagnostics quanh winner để hợp thức hóa winner. Diagnostic sampling vẫn là một phần của model development: có quyền chạy backtests, chọn vùng/recipe, nhưng không được gọi đó là independent OOS.

Dossier có thể được reuse nếu identities, information rights, scope và validity còn khớp. Không bắt chạy lại cùng diagnostics mỗi invocation. Nếu thiếu artifact hoặc contract đã đổi, planner yêu cầu chạy phần phụ thuộc bị thiếu/thay đổi.

Đường Mode 5 legacy phải còn reproduce được; không đột ngột bắt tất cả consumer cũ đổi API. Legacy output không được mang badge `diagnostics_first_certified` nếu chưa chạy quy trình mới.

## 1.2 Mode 5 tìm gì?

Mode 5 thực hiện **full-development-sample robust static calibration**: chọn một parameter configuration hoặc một fixed policy configuration, để giữ trong deployment horizon đã đăng ký. Nó không chứng minh params sinh lời trong mọi thị trường tương lai.

Bốn khái niệm không nhập làm một:

| Khái niệm | Định nghĩa cho guide này |
|---|---|
| Fixed-parameter deployment | Không retune external params trong một deployment horizon đã định |
| Parameter robustness | Kết quả không sụp đổ dưới perturbations hợp lệ đã thực sự evaluate |
| Environment robustness | Chất lượng/risk không phụ thuộc quá mức một environment trong tập nghiên cứu |
| Economic utility | Kết quả net trên account/risk allocation với costs và constraints rõ ràng |

Một fixed configuration vẫn có internal adaptation. A-HMA có adaptive-length recursion; không được thay thành fixed HMA rồi tuyên bố Mode 5 tốt hơn. Họ strategy trend không bị loại a priori. Một alpha có thể phù hợp Mode 4, Mode 5, cả hai, hoặc chưa đủ evidence để đề xuất.

**Không được dùng:** “alpha có edge thật phải lời ở mọi regime”, “invariance vĩnh viễn”, “loại 100% bias”, “Sobol quét hết không gian”, “CMA-SAM giải quyết mọi canyon”.

## 1.3 Đúng khung chính nhưng giới hạn đúng claim

Giữ ba hướng kinh tế:

1. Tìm cấu hình có floor/low-tail tốt qua environments.
2. Tìm vùng tham số có local downside nhỏ, không chỉ một peak đẹp.
3. Cân bằng environment quality, flatness, uncertainty và mandate constraints bằng composite đã version.

Giữ bốn selector slots:

```text
full_dro_cvar
full_sam_basin
full_pareto_chebyshev
full_alpha_adaptive_invariant
```

Tên là compatibility slots, không tự chứng nhận thuật toán bên trong. Mỗi slot bắt buộc có `selector_version`, `formula_id`, input metric contracts và meaning. Existing legacy formulas giữ tên/version replay riêng; không silently đổi semantics của artifact đã lưu.

## 1.4 Hai gates, không một cổng “tốt/xấu”

**Technical validity — blocking:** source/route mismatch, unsupported execution, invalid timing, thiếu mandatory metrics, không đủ dữ liệu để thực hiện phép đo đã claim, lỗi numerical, data leakage trong scope, incomplete panel bị ngụy trang complete.

**Research advisory — không phán quyết tuyệt đối:** regime dependence, uncertainty rộng, candidate bank hẹp, local fragility cao, ít opportunities, recipe chưa có ưu thế rõ. Có thể tiếp tục nghiên cứu với warnings và override có lý do; không đổi override thành chứng nhận invariance.

Dossier là bắt buộc. Dossier trung thực có thể nói `INCONCLUSIVE`, `NO_RECIPE_CLEARLY_PREFERRED` hoặc `NO_SUPPORTED_CONFIGURATION_IN_TESTED_SET`. Đó không phải lỗi kỹ thuật và không phải lý do rerun đến khi thắng.

## 1.5 Phạm vi và điều không làm

Primary verification dùng đúng bốn canonical alpha trong upload, trước hết trên BTCUSDT và các cohorts của bundle đã có. Cross-symbol/general-market conclusions chỉ mở sau protocol riêng; không tự phóng to thành ma trận toàn crypto/Vietnam/options.

Giữ QuantBT làm authority của order/fill/accounting/fees/funding/margin và metric canonical đã support. Không viết một backtest engine trong `alpha_profiling`.

Không đổi Mode 1–4 hoặc meta-selector Mode 4. Không tạo Mode 6. Không port strategy research features vào core. Không bật regime switching trong deployment Mode 5: dual-regime ở đây là **evaluation views**, không phải live parameter-switching controller.

Không sử dụng presampled full-set-tuned configs như clean historical seeds cho nested evaluation. Chúng được phép là diagnostic fixtures/retrospective controls với lineage rõ.

---

<a id="chapter-2"></a>
# Chương 2 — Kế thừa QuantBT hiện tại và ranh giới kiến trúc

## 2.1 Current-source mapping là nhiệm vụ cụ thể, không tái audit mọi thứ

Spec gốc ghi các locations của `evaluate_params_is`, `_score_is_subperiods`, DBSCAN plateau và public Mode 5 trong một source snapshot. Những dòng đó không chứng minh các upgrades Mode 4 gần nhất còn thiếu. M5-01 phải map symbols thực và ghi:

| Thành phần | Reuse bắt buộc nếu đã có | Delta được phép |
|---|---|---|
| Sampler factory/registry | TPE, multivariate/group TPE, CMA-ES, Sobol theo support thực | Stage/objective compatibility và diagnostics adapters |
| ParamSchema / feasibility | bounds, step/log, conditional keys, effective normalization | Activity map, diagnostic designs, coupled geometry |
| Prepared evaluator | signal/target/event/intrabar routes đã certify | Candidate/environment panel orchestration |
| WFO runtime | public Mode 5, Mode 4 causal evaluation contracts | Diagnostics prerequisite và new objective/selector hooks |
| Metric reducers | account equity, fees, funding, trade ledger, return moments | PSR/tail/HAC/diagnostic reducers còn thiếu |
| Trial/evaluation store | IDs, duplicate reuse, source lineage, statuses | Evidence graphs, diagnostics matrix references |
| Rust/batch substrate | native execution, prepared handles, bounded workers | Pure numeric reductions khi có profile chứng minh cần |

Module đã có chức năng tương đương → extend/hợp nhất. Không tạo registry hoặc cache thứ hai chỉ để khớp tên trong tree đề xuất.

## 2.2 Mode 5 data contract

Full-sample trong Mode 5 nghĩa là **full allowed development/calibration scope**, không phải mọi data hiện có trên disk. Metadata tối thiểu:

```json
{
  "methodology": "mode_5_full_robust",
  "purpose": "robust_static_calibration",
  "full_sample_used_for_selection": true,
  "validation_claim": "none_full_sample_calibration",
  "diagnostics_required": true,
  "diagnostic_dossier_id": null,
  "calibration_plan_id": null,
  "external_validation_refs": [],
  "status": "PLANNED"
}
```

Schema minh họa, chưa phải response từ package. `train_index=test_index=full_index` của legacy contract không phải independent train/test. Giữ raw legacy metadata, thêm explicit role để người đọc không hiểu nhầm.

Một repeated-origin experiment có thể gọi Mode 5 tại từng historical origin và giữ params cố định cho horizon tiếp theo. Đó là **validation của static-calibration procedure**, không sửa Mode 5 thành adaptive Mode 4. Tại mỗi origin, toàn diagnostics/scaler/environment construction/recipe choice phải nằm trước origin tương ứng.

## 2.3 Kế thừa sampler upgrades mà không vô tình bật meta

Bốn sampler families đã thảo luận cho Mode 4 được map tới actual config, không hardcode class names từ docs stable:

- Legacy/univariate TPE.
- Multivariate/group TPE khi actual version và search shape hỗ trợ.
- CMA-ES cho continuous/mixed-integer supported subspaces; categorical routing/fallback hiển thị rõ.
- Scrambled Sobol/QMC cho declared static subspace và diagnostic design.

Sampler-only không bật meta-learning. Meta Mode 4 dùng matured historical OOS labels không tự migrate thành Mode 5 recipe router. Mọi `source_trials`, warm-start hoặc priors phải khớp parameter representation, objective version, execution contract, source origin và allowed cutoff. Có thể reuse parameter coordinates mà không reuse objective values sai đơn vị.

Docs kỹ thuật nói rõ QMC phụ thuộc search-space inference/first trial; CMA-ES có giới hạn categorical. Chúng là constraints cần kiểm tại actual installed version, không phải lệnh nâng Optuna lên bản `stable` mới nhất [S4–S6].

## 2.4 Financial boundary và route qualification

Tối ưu vectorized/prepared là ưu tiên, nhưng không được xóa semantics để chạy nhanh:

- A-SC có thể dùng target/`pct_equity` khi long-flat, sizing, execution timing và rebalancing contract khớp; phải qualify, không suy từ tên endpoint.
- A-HMA/A-VWAP cần protection, gap/technical exits và amendments đúng. Dùng intrabar/event native của QuantBT phù hợp.
- A-HASH cần actual partial-ladder semantics. One-TP approximation không được dùng như cùng alpha.

Một shift signal không tự biến same-close engine thành next-open execution. Không thay cột close bằng open để lách routing.

`golden.py` trong ZIP là source cần inspect: có fixed-point helper dùng giả định fills và chỉ so exit bars. Chưa có bằng chứng các benchmark T1/T2 gọi helper đó. Không kết luận benchmark invalid chỉ từ helper; nhưng cũng không lấy helper làm oracle financial độc lập. Qualification dùng actual engine fills/order events và checks theo giá/qty/fee/timestamp/reason/priority/terminal state.

## 2.5 Ranh giới code được thay đổi

Làm trong branch/workspace nghiên cứu đã được phép. Default bảo vệ core checkout và alpha originals read-only; copy riêng editable, không hardlink. Không touch alpha khác, collector production, account keys hoặc trading services.

Nếu source Mode 4 đã upgrade trong QuantBT chính, snapshot/reuse đúng bản ấy bằng dependency hoặc candidate copy. Report nêu source SHA, imported origins, core/native pair, lock hashes. Không giả định ZIP alpha mới chính là code đã tạo T1/T2: cần so hashes/manifest, không thấy evidence thì `SOURCE_COMPATIBILITY_UNVERIFIED`.

---

<a id="chapter-3"></a>
# Chương 3 — Bảo toàn Baseline/T1/T2, sửa errata và audit bốn alpha

## 3.1 Evidence status

Trong lượt biên soạn guide này đã đọc 5 Markdown, 3 JSON của bundle và parse 24 Python files trong alpha archive. Đã tái tính bảng winners/dedup và một số toán học nhỏ; không chạy lại market experiment hoặc chứng nhận Rust runtime trên server.

Các evidence cũ giữ nguyên bytes. Tạo `evidence_errata.json` và `reanalysis/` mới. Không overwrite JSON để làm nó khớp bảng Spec. JSON cũng không tự là ground truth cuối: economics phải có trace/manifest để kiểm.

| Mã trạng thái | Dùng khi |
|---|---|
| `HISTORICAL_REPORTED` | Số liệu đọc từ artifact gốc chưa replay |
| `RECOMPUTED_FROM_ARTIFACT` | Tính lại bằng thông tin thực sự đủ trong artifact |
| `SOURCE_CONFIRMED` | Contract/hành vi thấy ở source đã hash |
| `MATH_ORACLE_CONFIRMED` | Phản ví dụ/identity toán học đã chạy; không market claim |
| `MARKET_VERIFIED` | Actual QuantBT execution trên snapshot hợp lệ và có evidence |
| `HYPOTHESIS` | Cơ chế cần thí nghiệm, không kết luận |
| `INSUFFICIENT_EVIDENCE` | Thiếu support/retention để kết luận |

## 3.2 Những gì bundle hiện đủ để làm

| Artifact | Nội dung export đã kiểm | Quyền reuse |
|---|---|---|
| D1/Baseline | 4 alpha × 5 candidate records × 4 environments = 80 records | Rank/floor/dispersion theo existing metric contract |
| D2/T1 | 12 sampler winners; 60 winner-environment records | Tái tạo bảng đã lưu, chọn fixtures chẩn đoán |
| D3/T2 | 16 selector/formulation rows; 11 unique parameter vectors theo alpha | Deduplicate replay; so winner metrics/components có sẵn |
| Full trial panels/return paths | Không nằm đầy đủ trong export này | Tìm caches thực trên server trước khi chạy lại |
| 25 mathematical probes của guide mới | Phụ lục C | Unit/reference evidence, không trading performance |

T2 có A-SC 3, A-HMA 2, A-VWAP 3, A-HASH 3 unique params. Hai selectors chọn cùng params không phải hai independent trading outcomes. Nhưng giữ cả selection records vì lý do chọn có thể khác.

## 3.3 Bảng T1 chính xác từ JSON

`metadata.samplers` là TPE, QMC và CMA-ES, không phải Random/TPE/QMC. Các số dưới đây có trạng thái `HISTORICAL_REPORTED`; rounding chỉ cho bảng, artifact gốc giữ full precision.

| Alpha | Sampler thực | Reported 2024-slice Sharpe | Return (%) | MaxDD (%) signed legacy | Fills |
|---|---|---:|---:|---:|---:|
| A-SC | `TPESampler` | 6.9516 | 5.4268 | -1.6565 | 3 |
| A-SC | `QMCSampler` | 2.5614 | 1.4661 | -1.2788 | 28 |
| A-SC | `CmaEsSampler` | 6.8749 | 5.3784 | -1.6565 | 3 |
| A-HMA | `TPESampler` | -4.2566 | -1.7191 | -2.4909 | 19 |
| A-HMA | `QMCSampler` | 1.9417 | 0.7891 | -0.9999 | 29 |
| A-HMA | `CmaEsSampler` | -0.2810 | -0.1200 | -1.3797 | 27 |
| A-VWAP | `TPESampler` | -2.5585 | -0.4107 | -0.6202 | 62 |
| A-VWAP | `QMCSampler` | 4.2526 | 0.5440 | -0.2374 | 20 |
| A-VWAP | `CmaEsSampler` | 1.9989 | 0.1940 | -0.3436 | 26 |
| A-HASH | `TPESampler` | 3.5997 | 1.8690 | -0.9015 | 49 |
| A-HASH | `QMCSampler` | 2.3724 | 1.2246 | -1.0405 | 49 |
| A-HASH | `CmaEsSampler` | 4.3776 | 2.5661 | -1.2282 | 21 |

Giữ đúng dấu DD trong artifact lịch sử. Canonical metrics phía sau dùng magnitude không âm; conversion được ghi trong metric contract, không âm thầm sửa JSON gốc.

T1 tune `sim_start=2021-01-09` đến `2021-02-15`; stress/holdout slice 2024 có `sim_start=2024-02-01`, `end=2024-03-15`, khoảng 43 ngày theo hiệu hai mốc. Không gọi đây là toàn năm 2024. Baseline cũ có sim_start khác ở một số windows; không so trực tiếp nếu scored intervals khác.

Observation giữ được: QMC winners có OOS Sharpe dương ở cả bốn alpha trong T1. Observation không giữ được: QMC vô địch toàn diện, TPE luôn overfit, trend alpha không thể fixed-parameter. T1 A-HMA/QMC có Sharpe +1,94; đó chưa phải long-horizon robustness nhưng đủ chặn kết luận tuyệt đối từ T2.

## 3.4 Bảng T2 chính xác từ JSON

| Alpha | Formulation ID lịch sử | Trial | Reported 2024-slice Sharpe | Return (%) | MaxDD (%) signed legacy | Fills |
|---|---|---:|---:|---:|---:|---:|
| A-SC | `MINMAX_REGRET_DRO` | 16 | 3.3806 | 1.9451 | -0.8798 | 48 |
| A-SC | `FLATNESS_SAM_PLATEAU` | 9 | 3.6179 | 2.9861 | -1.7164 | 16 |
| A-SC | `LORO_CROSS_VALIDATION` | 16 | 3.3806 | 1.9451 | -0.8798 | 48 |
| A-SC | `NSGAII_PARETO_KNEE` | 96 | 4.9293 | 3.4529 | -0.8942 | 47 |
| A-HMA | `MINMAX_REGRET_DRO` | 59 | -2.7492 | -1.3019 | -1.4650 | 33 |
| A-HMA | `FLATNESS_SAM_PLATEAU` | 95 | -2.5745 | -0.8208 | -1.1344 | 35 |
| A-HMA | `LORO_CROSS_VALIDATION` | 59 | -2.7492 | -1.3019 | -1.4650 | 33 |
| A-HMA | `NSGAII_PARETO_KNEE` | 95 | -2.5745 | -0.8208 | -1.1344 | 35 |
| A-VWAP | `MINMAX_REGRET_DRO` | 90 | 1.9419 | 0.1483 | -0.2079 | 10 |
| A-VWAP | `FLATNESS_SAM_PLATEAU` | 14 | 4.2526 | 0.5440 | -0.2374 | 20 |
| A-VWAP | `LORO_CROSS_VALIDATION` | 90 | 1.9419 | 0.1483 | -0.2079 | 10 |
| A-VWAP | `NSGAII_PARETO_KNEE` | 70 | 3.5053 | 0.2800 | -0.2750 | 16 |
| A-HASH | `MINMAX_REGRET_DRO` | 58 | 5.0198 | 2.4759 | -1.0093 | 17 |
| A-HASH | `FLATNESS_SAM_PLATEAU` | 73 | 4.7830 | 2.6733 | -0.9609 | 26 |
| A-HASH | `LORO_CROSS_VALIDATION` | 58 | 5.0198 | 2.4759 | -1.0093 | 17 |
| A-HASH | `NSGAII_PARETO_KNEE` | 3 | 2.2565 | 1.2571 | -0.7231 | 34 |

Formulation ID giữ nguyên để tra cứu; nó không chứng nhận implementation là đúng NSGA-II, LORO, minimax regret hay CVaR. Xem corrections trong Chương5–6 trước khi phát hành canonical methods.

Một số fills/DD trong Spec khác JSON (ví dụ HASH/DRO 17 fills, VWAP/SAM 20 fills, SC/SAM 16 fills và DD khoảng −1,7164%). T2 report mô tả paired QMC candidate panel + selector comparisons, không tự là benchmark của bốn search algorithms khác nhau.

T2 không có actual PSR arrays, covariance-neighborhood matrix V1.1 hoặc hard-gate evaluation đầy đủ. Không ghi các method mới đã được T2 chứng minh. `NSGAII_PARETO_KNEE` và `LORO_CROSS_VALIDATION` giữ như historical formulation IDs, thêm algorithm-meaning caveat nếu source cho thấy thực là Pareto post-selection/range penalty.

## 3.5 Recipe observations không phải quy luật alpha family

| Observation | Hypothesis đúng để thử tiếp | Điều không suy ra |
|---|---|---|
| HASH/worst-floor tốt ở T2 | Environment-floor có thể chọn trade-off phù hợp HASH | Breakout bắt buộc dùng DRO |
| VWAP/SAM tốt ở T2 | Local downside probes có thể giúp tránh peak | Mean-reversion bắt buộc dùng SAM |
| SC/Pareto tốt ở T2 | Compromise giữa environments đáng thử | Composite alpha luôn dùng NSGA-II |
| HMA selectors T2 âm | Candidate pool/transfer/horizon cần diagnostic | Trend family không thể dùng Mode 5 |

2024 đã được dùng để hình thành các hypotheses trên; từ nay giữ `EXPLORATORY_REVIEWED_2024`. Không tiếp tục gọi 2024 là untouched confirmation của recipe được chọn nhờ bảng đó. Việc mở thêm dữ liệu hiện có không tự tạo holdout sạch nếu human/model search đã dùng nó.

## 3.6 Alpha source inventory và targeted deltas

Các locations ở đây tham chiếu **alphas.zip mới**, không raw source/old lab đã audit trước đó. Hash trong Phụ lục A.

### A-SC — SignalCombine long-flat

- `a_sc.py:70–159`: signal/indicator computation; `:212–228` prepare; `:230–285` decisions.
- `coeff=int(self.params['coeff'])` tại khoảng dòng223: schema mới nên dùng effective integer domain. Legacy decimal inputs giữ migration log, không sửa âm thầm kết quả replay.
- Long-flat semantics được giữ; không thêm short để “sửa bear regime”.
- Volume fallback/RSI-MFI convention và scalar/vectorized path cần parity.
- T1 winner có 3 fills cần daily/campaign/exposure audit; không lấy 3 làm N của daily PSR, cũng không coi đó là nhiều independent trades.
- Targeted evidence: coefficient collisions; indicator-to-order mapping; long-held exposure control; return/tail sensitivity theo AP/threshold.

### A-HMA — Adaptive HMA có internal state

- `a_hma.py:32–37`: canonical stop modes + explicit legacy aliases; unknown mode bị reject ở `_validate_params:102–122`. Lỗi alias cũ không được báo như còn tồn tại.
- `prepare:132–194`: min/max lengths tham gia seed, clamp và recursion. `min_length` không structurally dead.
- `IGNORED_KNOBS`: `sl_mult`, `double_up`, `time_ms`, `volume` trong version hiện tại phải hiện ignored; không thêm chúng vào active search.
- Fixed params không freeze effective length. Profile phải trả dynamic/minor length paths hoặc summaries, clamp frequency, trạng thái thích nghi và interaction với ATR fast/slow.
- Test min-length trong một window không chạm clamp chỉ có thể kết luận low observed effect ở window đó; cần paths khác trước khi prune.
- Targeted evidence: candidate QMC/T1 và hai unique HMA T2 vectors dùng cho diagnostic transfer; những fixtures này đã được chọn hậu nghiệm, không là clean recipe-validation sample.

### A-VWAP — HTF/conditional exits và warmup

- `htf_ema_available_at:41–79`; `ema_convergence_bars:82–87`; `prepare:146–176`; decision/amendment khoảng192–279.
- Warmup phụ thuộc EMA span và effective HTF bucket count. Với epsilon 10^-3, spans30/40/200/700 cần104/139/691/2418 buckets theo helper. Common scored interval phải như nhau; preload khác nhau được phép nhưng không chấm candidate dài trên ít ngày hơn.
- `exit_at_vwap`, `time_stop_on` là branches; `time_stop_bars` inactive khi time-stop off. Không dùng Euclidean perturbation để biến một branch boolean thành continuous axis.
- Dynamic amendment chỉ hiệu lực sau observation/effective phase đã xác định; phải trace actual QuantBT handling.
- Targeted evidence: branch toggles, common warmup, stale/missing HTF, amendment active vs disabled, three T2 vectors.

### A-HASH — Ladder/campaign rather than fill-count alpha

- `a_hash.py:181–247`: quantization/ladder; `:249–274`: actual-fill levels và cooldown.
- TP1=40%, TP2=40% remaining tương ứng 40%,24%,36% entry quantity trước lot rounding. Không tự đổi thành 40%,40%,20%.
- Rungs cùng campaign; partial fills không phải independent trades. Cooldown bắt đầu khi thật sự flat, không mỗi partial.
- Feasibility: positive stop, ordered RR levels, 0<fractions<=1, quantity step/minimum, residual position/dust. Constructor/helper chưa chắc chặn mọi input; kiểm schema lẫn boundary.
- `quantize_ladder` gọi QuantBT helper: reuse, không tính rounding riêng trong profiler.
- Targeted evidence: actual ladder fills/fee allocation, stop trên remaining quantity, same-bar multiple hits/priority, cooldown, tail stats trước/sau campaign aggregation.

## 3.7 Source compatibility và reuse decision

Mỗi historical execution có bốn khả năng:

```text
EXACT_REUSE
REANALYZE_ONLY
REPLAY_REQUIRED_FOR_REQUESTED_METRIC
INCOMPATIBLE_ECONOMICS_OR_ALPHA
```

Code hash thay đổi không nhất thiết mọi execution invalid; cần semantic diff và equivalence tests. Ngược lại, cùng `canonical_v1` string không đủ nếu code bytes khác. Map alpha source, dependencies, timing, sizing, fee/rounding, warmup, price data và terminal rules.

Nếu chỉ formula selector đổi trên cùng verified metric panel → reselect không rerun simulation. Nếu raw return path đã có → thêm PSR/tail reducer không rerun execution. Nếu only summary thiếu skew/serial structure → tìm path hoặc replay targeted candidate; không suy moments từ fills_count.

---
<a id="chapter-4"></a>
# Chương 4 — Diagnostics cockpit: thiết kế phép đo trước khi tuning

## 4.1 DiagnosticStudy là đơn vị khoa học, không một lần gọi optimizer

Một study phải freeze trước khi chấm result:

```text
alpha/version + effective parameter schema
market/data snapshot + allowed data roles
execution/sizing/cost/terminal contracts
primary outcome + guardrail metrics
candidate design + neighborhood design
historical anchors + rolling-state construction
support/uncertainty policy
sampler/selector battery + paired comparisons
compute/memory limits + cache reuse rights
validation and report policy
```

Các controls này làm diagnostics reproducible; không cấm discovery học từ kết quả. Muốn đổi design sau khi xem results, tạo revision và giữ attempt history. Không sửa registry cũ thành “đã đăng ký từ đầu”.

Mọi hypothesis cần: câu hỏi → estimator → dữ liệu được phép → prediction hoặc expected observation → rival explanations → test → kết luận được phép. Phase report phải chỉ rõ **test có khả năng phát hiện điều gì và có thể bỏ lỡ điều gì**.

## 4.2 Candidate × Environment × Metrics: bảng gốc duy nhất

Định nghĩa:

\[
Y_{i,e,s}=(U,R_{net},SR,PF,MDD,ES,Turnover,Exposure,Support,Status)_{i,e,s}.
\]

`i` là effective candidate, `e` environment/evaluation view, `s` scenario/seed khi stochastic có thật. Không tạo seed axis giả cho deterministic backtests rồi coi repeated values độc lập.

Schema tối thiểu cho một row:

```text
study_id / diagnostic_revision / alpha_id / candidate_id
raw_params_digest / effective_params_digest / branch_id
execution_id / trial_refs[] / scenario_id
environment_id / environment_family / estimand_id
calibration_origin / start / end / warmup_start / available_cutoff
actual_bar_count / exposure_days / closed_campaigns / fills / open_campaigns
metric_contract_ids / metric_values / null_reasons
cost_contract / initial_state / terminal_policy / actual_endpoint / actual_backend
source/data/result digests / compute_status / data_role / evidence_refs
```

Năm states không nhập làm một: structural invalid, runtime failed, valid no-trade, valid unprofitable, valid profitable. Valid zero return vẫn là economic outcome; Sharpe undefined thì giữ null và reason. Không biến undefined thành +infinity, arbitrary best score hoặc silently drop environment.

Khi hai candidates có cùng effective params, reuse execution nhưng giữ trial IDs. Khi khác params mà trùng output trên một dataset, chỉ ghi `behaviorally_equivalent_on_scope`, không tuyên bố structural equivalence toàn miền.

## 4.3 Sáu ma trận derived bắt buộc trong dossier

| Ma trận | Minimum outputs | Câu hỏi khoa học |
|---|---|---|
| Parameter × representation/behavior | active mask, ranges, cast/step, behavioral effect, sensitivity | Tham số đang điều khiển cái gì? |
| Candidate × environment | full metric vectors, support, statuses | Trade-off giữa các điều kiện ra sao? |
| Center × neighbor × environment | requested/effective perturbation, downside, quality/risk pass | Flat basin hay chỉ top trials? |
| Environment × environment | Spearman, top-set overlap, transfer/regret, paired support | Rankings và gần-optimal regions thay đổi thế nào? |
| Recipe × split × seed | selections, utility, risk, local fragility, uncertainty, resource cost | Recipe nào đáng ưu tiên và độ chắc chắn? |
| Candidate × execution stress | base/stress costs, latency, gap/protection effects, rank changes | Kết luận có phụ thuộc execution assumptions không? |

Mỗi heatmap phải có masks cho chưa tested/incomplete/undefined. Nội suy chỉ visualization, không thêm observations. Hai environment views dùng cùng dates phải giữ dependence; không nhân evidence bằng đổi nhãn.

## 4.4 Trục 1 — Execution mechanics và economics profile

### 4.4.1 Financial streams phân biệt

- Daily account return stream: unrealized marks, fees, funding, zero-return observations, calendar convention.
- Closed-campaign PnL stream: entry đến final close, partial fills và costs được gộp theo campaign.
- Execution event stream: accepted/rejected orders, fills, qty/price/fees, amendment, terminal actions.

Không dùng moments của campaign PnL với N daily bars; không dùng count partial fills làm số independent trades. Open/censored campaigns phải được hiển thị với mark-to-market contribution, không bỏ khỏi account risk.

### 4.4.2 Metrics tối thiểu

Return/CAGR theo contract, Sharpe/raw-vs-penalized, Sortino nếu support, PF campaign/return-step với tên khác nhau, win rate/expectancy, positive MDD magnitude, tail expected shortfall, fees/funding, turnover, exposure, holding median/p90/max, number of campaigns, concentration of PnL by campaign/day, terminal-close contribution.

`holding<2h` chỉ là horizon descriptor, không tự dán nhãn HFT. Bracket protection là mechanics descriptor, không invariance certificate.

### 4.4.3 Economic tests cần chạy bằng QuantBT

1. Same candidate, same data, cost multipliers được đăng ký: xem net utility và rank thay đổi; replay actual strategy nếu costs/equity ảnh hưởng decisions.
2. Quantity/fee/campaign fixtures: same fills → account/campaign totals reconcile; chia fill có thể đổi rounding/minimum-fee, nên equivalence test phải nêu điều kiện.
3. Gap test: stop không được hứa fill đúng trigger trong gap nếu contract dùng gap-open; actual fill làm bracket invalid phải xử lý đúng.
4. High/low ambiguity test: cùng OHLC có hai paths plausible; declared pessimistic/order policy được giữ, không lựa path có lợi.
5. Terminal rule test: mark-only và force-close là hai contracts; ảnh hưởng cost/Sharpe/holding phải được ghi. Không mix trong candidate ranking.
6. Exposure control: so fixed-risk/sizing hoặc market-direction comparator train-calibrated khi cần giải thích edge; không scale bằng realized OOS vol rồi gọi deployable.

Các stress diagnostics không cần thêm L2/latent book mặc định. Dùng các execution capabilities đã có trong QuantBT, actual same contract ở mọi candidate/recipe.

## 4.5 Trục 2 — Parameter geometry và landscape

### 4.5.1 Effective domain trước normalized coordinates

Với parameter `p_j`, define transformation `g_j`: linear/log/categorical/conditional/coupled, cùng finite bounds và grid steps. `z_j=(g_j(p_j)-a_j)/(b_j-a_j)` chỉ dùng cho active numeric dimensions có domain hợp lệ.

- Fixed/inactive keys không tăng dimension hay denominator.
- Categorical: branch distance/discrete neighbors rõ, không PCA trực tiếp trên label integers.
- Ordered/coupled parameters: khai báo latent positive spans hoặc feasible constraints. Nếu reparameterize, log distribution thay đổi; không lén đổi search prior.
- Duplicate do int/lot cast: giữ raw/effective pair, reuse execution khi contract cho phép.
- Zero-width domain: excluded với status fixed, không chia cho0.

Một distance Gower-like để diagnostics:

\[
d(\theta,\phi)=\frac{\sum_{j\in A}w_j d_j(\theta_j,\phi_j)}{\sum_{j\in A}w_j}.
\]

Active-branch mismatch có policy riêng. Scales/weights lấy từ registered schema/reference, không từ min/max của trials đã tình cờ chạy. Thêm một outlier trial không được tự làm các candidates cũ gần nhau hơn.

### 4.5.2 Global sensitivity

Với independent inputs đã được định nghĩa và output `Y`:

\[
S_j=\frac{Var(E[Y\mid X_j])}{Var(Y)},\qquad
S_{Tj}=\frac{E[Var(Y\mid X_{-j})]}{Var(Y)}.
\]

Sobol/Saltelli dùng structured A/B/cross matrices. `calc_second_order=false` cần `N(D+2)` input rows; true cần `N(2D+2)` [S3]. Không áp hàm analyze lên arbitrary TPE list rồi gọi đúng design.

Tính sensitivity riêng cho utility, drawdown/tail, turnover và opportunities. Một parameter ST nhỏ đối với Sharpe có thể ảnh hưởng risk. Report CI/convergence, constant-output status và sampling distribution. Không clip một negative finite-sample estimate về0 rồi quên uncertainty.

Conditional/coupled space không thỏa independent-input assumption: phân tích trong fixed branches hoặc independent latent variables đã khai báo; labels phải nói sensitivity theo representation đó. Không bỏ invalid rows của Saltelli tùy tiện vì phá cấu trúc estimator. Có thể dùng local perturbation/permutation/surrogate screening nhưng phải đặt tên đúng và validate surrogate, không gọi là exact Sobol.

### 4.5.3 Diagnostic domain không bị ép nhỏ chỉ để rẻ

Coverage khởi đầu có thể128 rồi256 unique feasible configs cho alpha mới, nhưng budget theo actual active dimensionality. Đây không bảo đảm phủ mọi corners. Nếu dùng full space >10dims mà coverage mỏng, trả `INSUFFICIENT_COVERAGE` cho các kết luận cần nhiều hơn.

Một 2–3-key-parameter subspace là useful targeted study, không bằng chứng mọi parameter còn lại dead. Các fixed values phải được chọn bằng development/protocol, không lấy fullset winner rồi gọi subspace clean OOS.

### 4.5.4 Local robustness phải chủ động và độc lập sampler

Từ broad discovery lấy vài centers có quality, không chỉ một winner. Generate perturbations theo schema seed/radii đã đăng ký. Kiểm mọi feasible neighbor, kể cả lỗ/risk breach. Covariance của top trials chỉ giúp chọn thêm hướng, không là thước đo volume của plateau.

Giữ riêng các tập:

```text
exploration_trials
geometry_fit_candidates
selection_probes
local_validation_probes
```

Nếu dùng probes để chọn candidate, probes đó là selection data. Một tranche probe seeds/directions khác dùng làm local validation; vẫn trên market development nên không gọi temporal OOS. Không dùng cùng perturbed panel để vừa chọn và “chứng minh independent” kết quả.

### 4.5.5 Ma trận stable basins

Mỗi center có primary quality `U(center)`, downside distribution, `F_max`, lower-tail utility trên neighbors, quality-survival fraction, boundary clipping rate, unique effective probes, missing/error count, per-dimension and joint-direction coverage.

Flat nhưng âm không đủ tốt. Peak tốt nhưng surrounding collapse được báo fragile. Có thể có một vùng hẹp economic-valid do instrument constraints; không penalize chỉ vì không bước ra ngoài feasible manifold. Tuy nhiên không được projection nhiều probes thành một điểm rồi gọi đã kiểm nhiều directions.

## 4.6 Trục 3 — Dual-perspective environments và chronology

### 4.6.1 Perspective A: domain historical anchors

Giữ các stress anchors trong bundle để reproduction/development. Record exact scored start/end và preload, không dùng label “Bull 2021” thay timestamps.

Thêm broad contiguous development path hoặc broader contiguous blocks nếu cache có. Chỉ bốn selected episodes thuận mắt không chứng minh all-development robustness. Nếu thiếu broad path, scope của dossier phải là `anchor_scope_only`; full-calibration claim cần actual full allowed data evaluation.

Các anchors có thể được xác định bằng hindsight **khi phục vụ calibration hiện tại trên development đã biết**. Nhưng không dùng một hindsight-selected anchor như causal regime signal tại thời điểm lịch sử. Câu hỏi evaluation khác → estimand khác.

### 4.6.2 Perspective B: endogenous causal partitions

Ví dụ realized volatility/trend/activity từ closed bars, thresholds fit đúng cutoff. Rolling feature không đảm bảo quantile boundaries causal nếu `qcut` trên cả future window. Fit scaler/threshold/model trên từng inner train và apply forward cho validation.

Trong full-development calibration, historical retrospective partitions có thể hợp lệ với nhãn `asof_calibration_descriptive`; nếu claim causal transfer, phải có decision-vintage labels. Không cần một project regime-model mới cho Mode5; reuse provider/lab module đã có, ghi provenance đúng.

### 4.6.3 Hai chế độ đánh giá không tráo

**`CONTINUOUS_PATH_ATTRIBUTION`:** simulate chronological path liên tục một lần, rồi group existing observations/campaign attribution theo labels. Không splice các ngày cùng regime thành chuỗi giá giả. Với một trade kéo dài qua state boundary, account daily PnL chia theo actual marks; campaign attribution entry-state hoặc duration-weighted phải được named riêng.

**`CONTIGUOUS_RESET_EPISODES`:** mỗi episode có warmup, initial-state và terminal rules riêng. Đây là counterfactual diagnostic, không tự là continuous live result.

Không lấy episode Sharpe mean làm whole-path Sharpe. Day durations, gaps và missingness phải đúng metric contract; disjoint regime subset có thể có descriptive conditional moments, không annualize theo độ dài ghép giả rồi gọi annual trading performance.

### 4.6.4 Overlap và environment weights

Một ngày có thể nằm trong domain anchor và rolling bucket. Báo panels riêng, không stack như độc lập. Nếu tổng hợp, define weights/family policy và effective information overlap. Bootstrap phải giữ shared days/common shocks giữa candidates/arms.

Equal-duration, duration-weighted và equal-scenario weights là các mandates khác nhau. Freeze trước selection. Không cho duplicated environment row tăng influence chỉ vì copy artifact.

### 4.6.5 Stress coverage và support

Report duration, exposure, campaigns, state episodes, zeros, valid-observation count, repeated market events, input-quality flags. Không bắt state ít trade phải có positive Sharpe bằng cách thay no-trade thành +0; giữ economic path và uncertainty.

Dossier có thể cần additional window để phân biệt hypothesis. Chọn window bằng rules/development, không tìm một window sau khi xem performance rồi giả đó là neutral confirmation.

## 4.7 Trục 4 — Invariance, transfer và evidence strength

### 4.7.1 Rank correlation chỉ là một diagnostic

Tính pairwise Spearman trên common valid candidates, report ties/missingness/count. Không correlate winners-only list rồi gọi full rank stability. Bootstrap candidate-generation seeds hoặc time blocks phù hợp câu hỏi, không iid shuffle market rows.

`I_inv<0.4` là legacy heuristic có thể giữ trong reproduction, không là điều kiện cần của robust candidate. Một candidate tốt nhất ổn định vẫn có thể tồn tại khi các ranks phía dưới đảo nhau. Test oracle ở Phụ lục C minh họa điều này.

### 4.7.2 Near-optimal set và regret matrix

Với finite registered candidate set `C`, define:

\[
b_e=\max_{\theta\in C_{valid}}U_e(\theta),\quad
G_e(\delta_e)=\{\theta: U_e(\theta)\ge b_e-\delta_e,\;Risk_e(\theta)\le Limit_e\}.
\]

Report intersection/overlap của `G_e`, max regret theo candidate, local robustness của các members. `b_e` là finite-panel benchmark, không optimum toàn không gian. Nếu không có intersection, chưa chứng minh không có robust configuration ngoài panel.

`delta_e` là economic tolerance hoặc scale-aware preference đã đăng ký; không chọn để giữ winner. Empty set phải có reason: poor quality, insufficient support hay hard risk failure.

### 4.7.3 Leave-one-environment-out đúng nghĩa

Với panel không dùng held environment để adaptive search:

\[
\hat\theta_{-e}=Select(Y_{C,\mathcal E\setminus e}),\quad V_e=U_e(\hat\theta_{-e}).
\]

Lưu selection mỗi excluded environment, omitted inputs, held score. Range penalty không phải LORO. Fixed panel xây từ neutral QMC trước scores có thể dùng leave-out selector diagnostic rẻ; candidate set adaptive trên mọi environments thì chỉ claim **conditional fixed-panel leave-out**, không selection-independent search validation [S10].

LORO sử dụng future regimes để chọn cho past held regime là retrospective transfer analysis, không historical live forecasting. Outer chronological validation vẫn là gate của recipe deployment.

### 4.7.4 Decay theo cùng fixed params

Giữ raw fields:

\[
D^{SR}_{i,o}=SR^{dev}_{i,o}-SR^{fwd}_{i,o},\quad
D^{g}_{i,o}=g^{dev}_{i,o}-g^{fwd}_{i,o},
\]

với `g` là growth-rate hoặc mean net return theo cùng time convention. Với PF hữu hạn, dương và đủ campaign support:

\[
D^{PF}_{i,o}=\log PF^{dev}_{i,o}-\log PF^{fwd}_{i,o}.
\]

Không dùng ratio `(IS-OOS)/IS` khi IS gần0/âm, không dán >100% là structural impossibility. Export raw ratios chỉ nếu denominator eligibility pass. Sharpe/return/PF decay phải đi cùng actual forward utility, drawdown, exposure và support.

**Lower decay không tự là tốt:** một recipe có IS tệ hơn nhưng OOS không đổi sẽ giảm decay. Vì vậy primary comparison cần forward economic quality và decay joint, không thưởng shrink IS đơn thuần.

Parameters giữ cố định trong một forward horizon; repeated origins là validation repetitions. Không đưa feedback của chính horizon chưa mature vào profiler/recipe selection trước origin.

### 4.7.5 Bỏ gate “ba điều kiện suy ra Mode4”

Thay bằng result vector:

```text
financial_validity
parameter_robustness_evidence
environment_support
transfer_evidence
statistical_uncertainty
mandate_constraints
mode5_research_advisory
```

Một mandate có thể yêu cầu floor dương từng scenario, nhưng đó là business constraint có version, không theorem cho mọi alpha. `min t<1.65` hoặc PSR thấp do mẫu nhỏ phải có trạng thái insufficient, không tự là proof negative.

Fixed candidate chọn trước, joint hypothesis “mọi environment vượt floor” có thể có intersection–union structure; không máy móc Bonferroni chỉ vì K regimes. Nhưng recipe/candidate/threshold đã search cần outer selection controls. Guide không cấp blanket multiplicity waiver.

## 4.8 Trục 5 — Return distributions, tail risk và economics

Tính daily skew/kurtosis, campaign skew/kurtosis và fill-cost distribution riêng. Ordinary kurtosis = excess kurtosis+3; record estimator và ddof. Không suy khoảng win rate từ một skew threshold duy nhất.

Loss `L=-r` trên daily account returns. Expected shortfall mức q dùng tail mean đúng định nghĩa, có fractional mass tại quantile nếu empirical atoms. Không cùng tên `CVaR` cho Q25 của regime scores và ES95 của daily losses.

Tail coverage gồm số tail observations, số distinct episodes, concentration và sensitivity với block choice. Ít tail events → wide uncertainty. Không dùng fitted Gaussian tail để chứng minh fat-tail robustness nếu không test model assumption.

Cần inspect gross-vs-net, fee drag, realized/unrealized, open/censored campaigns, terminal liquidation và loss concentrations. Các source của tails khác nhau:

```text
market move
execution cost/gap
position sizing/inventory
parameter discontinuity
terminal/reporting convention
```

Skew/risk profile gợi ý tests nào cần ưu tiên, không tự route SAM/DRO/Pareto theo alpha label.

## 4.9 Multi-hypothesis empirical battery: giữ năm chiều, làm rõ mỗi phép thử

| Battery | Hypothesis | Thiết kế chính | Rival explanation phải thử |
|---|---|---|---|
| B1 Floor resilience | Floor/tail-aware selection tốt hơn pooled winner ở weak environments | Same candidate panel, held diagnostic splits; quality/risk cùng contract | Chỉ bớt exposure hoặc bỏ trades |
| B2 Local flatness | Probes chủ động giúp tránh fragile peak | Same centers/probe budgets; schema vs covariance vs union; held directions | Covariance né chiều nhạy; top-filter selection bias |
| B3 Pareto compromise | Multi-environment trade-off cần compromise khác weighted max | Fixed panel/front; stable normalizers/preferences; leave-out sensitivity | Weights/utopia hậu nghiệm hoặc front chung không phân biệt selectors |
| B4 Temporal transfer | Một recipe giúp fixed params giữ forward quality/giảm decay | Fixed params trên chronological blocks/origins; same horizons/support | Lower IS alone, broad market exposure, one event |
| B5 Sampler response | Sampling recipe ảnh hưởng coverage/quality/stability | Same objective/budget/constraints; paired seeds where meaningful | Duplicates, fallback sampler, different compute or OOS selection |

B4 áp dụng cả bốn alpha, không một “test HMA” định sẵn failure. B5 so registry families actual; không chỉ Sobol vs TPE nếu Mode4 đã hỗ trợ variants phù hợp.

### Ba cấp so sánh không gộp

1. **Selector-only:** shared verified candidate panel → khác selection functions. Rẻ và nên làm trước.
2. **Sampler-only:** cùng objective/selector/budget → khác candidate generation. Không reuse winner-only table làm full sampler ranking.
3. **End-to-end recipe:** khác cả pipeline có predeclared diagnostic selection và outer validation. Đây mới là evidence cho auto-advisory.

Tất cả cần matched unique executions và actual visited bars, không chỉ100 trial labels. Same random seed không bảo đảm hai adaptive samplers đi cùng sequence. Wall-clock comparisons và fixed-work comparisons báo riêng.

## 4.10 Radar và advisory dossier

Radar là presentation view. Mỗi axis gồm raw statistic, direction, unit, normalization policy, support/uncertainty và matrix refs. Không hardcode thresholds sao cho bốn alpha ra đúng “winner” T2.

Tách:

- `AlphaQualityRiskProfile`: properties và evidence của alpha.
- `RecipeSuitabilityProfile`: candidate recipes được đo phù hợp ở mức nào.

Nếu cần 0–100 score, freeze scale theo mandate/reference cohort từ development; thêm OOS row không được thay scores cũ. Nếu chưa có scale đáng tin, hiển thị raw values, không bịa 50/100 cho unknown.

Recommendation đầu tiên là ordered shortlist + reasons, có `NO_CLEAR_WINNER`. Auto routing chỉ sau validation của toàn routing rule. Bốn benchmark alphas là regression/test cases, không đủ để huấn luyện taxonomy universal.

Mandatory dossier chứa: source/contract identity, all six matrices, coverage map, data-role ledger, model-free economic descriptors, statistical limitations, results mỗi battery, computation bill, unresolved hypotheses, suggested next targeted tests và `CalibrationPlan` proposal. Không xuất `DEAD_PRUNED` chỉ từ ST<0.02; không gắn badge `PRODUCTION_INVARIANT` từ radar.

---
<a id="chapter-5"></a>
# Chương 5 — Toán học canonical, objective families và uncertainty

## 5.1 MetricContract trước công thức tối ưu

Một numeric score không có units/role là invalid input cho selector. Phải freeze:

```text
return_series: daily_account | closed_campaign | other_explicit
return_definition: simple | log | pnl_on_frozen_capital
calendar: UTC daily / explicit session
annualization: 365 cho crypto daily nếu dùng reporting convention này
risk_free_rate: source, frequency, conversion
sample_count / ddof / skew-kurtosis estimator
initial equity before first scored observation
external cashflows and valuation sequence
MDD sign / ES loss convention / PF grouping
no_trade / zero_variance / bankruptcy / sparse_support handling
```

`raw_sharpe`, `penalized_objective`, `daily_mean_return`, `return_pct` và `PSR` không dùng thay thế tên trường. Nếu package hiện có một metric definition khác, giữ `quantbt_raw_metrics` rồi thêm derived canonical field có version; không ghi đè silently.

### Account/episode return

Với no external cashflow và equity dương:

\[
r_t=E_t/E_{t-1}-1,\qquad R_{[a,b]}=E_b/E_{a^-}-1.
\]

`a^-` là mark ngay trước block; block đầu dùng initial equity trước observation đầu. Nếu external flows có thật, dùng engine cashflow-adjusted metric đã định, không tự viết account kernel mới.

Money-PnL partition phải reconcile. Simple return của consecutive blocks compound, không cộng raw returns như dollars. Để so unequal environment durations, report growth rate/mean daily net return và elapsed days bên cạnh tổng return. Nếu E<=0, log/CAGR metric có thể undefined; bankruptcy là valid adverse outcome, không numerical failure được bỏ.

### Sharpe

\[
\widehat{SR}_{period}=\bar x/s_x,\quad x_t=r_t-r_{f,t},\qquad
SR_{annual}=\sqrt{A}\widehat{SR}_{period}.
\]

`A` là reporting convention, không chứng minh IID. Không dùng `sqrt(len(window))` làm annualization khi window lengths khác nhau. Days không trade nhưng vẫn có tài khoản phải theo same return contract; không loại zeros để tăng Sharpe.

### Drawdown / Profit Factor

\[
MDD=\max_t(1-E_t/\max_{u\le t}E_u)\ge0.
\]

Initial watermark bắt đầu từ `E_initial`, không tự reset khi chia regime attribution. Segment-reset drawdown có thể giữ như diagnostic riêng.

\[
PF_{campaign}=\frac{\sum_c\max(P_c,0)}{\sum_c\max(-P_c,0)}.
\]

`P_c` là net closed-campaign PnL với fee/funding allocation đã định. `PF_return_steps` là metric khác. Zero losses → infinity/undefined theo schema, không cap tùy ý để selector tưởng chất lượng cực tốt. All zero/no campaigns → null reason; open campaigns vẫn nằm trong account returns và reported separately.

## 5.2 PSR — giữ công thức, không nói nó xóa khác biệt sample

Classical plug-in version [S1]:

\[
\widehat{PSR}(SR^*)=
\Phi\!\left(
\frac{(\widehat{SR}_{period}-SR^*_{period})\sqrt{N-1}}
{\sqrt{1-\widehat\gamma_3\widehat{SR}_{period}
+\frac{\widehat\gamma_4-1}{4}\widehat{SR}_{period}^{2}}}
\right).
\]

`gamma4` là ordinary kurtosis. Tất cả moments cùng return series; N là số observations của series đó. PSR có asymptotic/stationarity/dependence assumptions; không gọi là posterior probability tuyệt đối alpha có edge. Nó phản ánh uncertainty trong Sharpe estimate, không thay economic preferences đối với tail risk.

Mandatory guards: N/support hợp lệ, finite moments, positive variance, positive denominator approximation; invalid → typed status. Không silently đổi kurtosis hoặc N để làm PSR đẹp. Nếu estimated moments không ổn, report uncertainty/alternative conservative analysis, không fill một default favorable.

**Oracle O01 đã chạy:** annual SR=1, A=365, N=43, gaussian moments, reference0 → PSR≈0,632689624 khi dùng SR daily. Dùng annual SR=1 trực tiếp cho≈0,999999939. Đây là mathematical counterexample, không khẳng định code Mode5 hiện tại đã mắc lỗi.

### Dependence-aware alternative

Không chỉ thay N bằng một heuristic ESS rồi gọi đó cùng PSR. Có thể dùng paired block bootstrap hoặc một Sharpe-SE estimator có contract riêng.

Một delta-method/HAC reference có influence function:

\[
\psi_t=\frac{x_t-\mu}{\sigma}
-\frac{\mu}{2\sigma^3}\big((x_t-\mu)^2-\sigma^2\big),
\]
\[
\widehat{\tau}^2=\widehat\Gamma_0+
2\sum_{h=1}^{H}w_h\widehat\Gamma_h,
\qquad SE_{HAC}(\widehat{SR})=\sqrt{\widehat{\tau}^2/N}.
\]

Bandwidth/kernel/moments/small-sample policy phải được freeze và validate. Chỉ gọi `sharpe_evidence_hac_v1`, không giấu nó dưới classical PSR. Đây là implementation proposal cần statistical oracle/calibration tests, không bắt buộc viết lại nếu existing statistics layer đã có implementation tương đương.

### PSR và multiplicity

PSR không kiểm soát mọi candidate/sampler/recipe searches. DSR là một additional diagnostic nếu có đủ trial/search/dependence information; không giả số trials độc lập bằng n_backtests, không suy DSR từ winner-only table [S2]. Nested whole-procedure validation vẫn là control chính.

Tối đa hóa PSR có thể chọn effect nhỏ có nhiều observations hơn effect lớn ít observations. PSR saturation gần1 có thể mất ranking resolution. Vì vậy economic quality constraints vẫn cần; p-values/confidence không thay return/risk trade-off.

## 5.3 Primary utility và score channels

`CalibrationPlan` phải chọn một channel rõ:

**`ECONOMIC_UTILITY_V1`:** example cho matched-horizon episodes:

\[
U_e(\theta)=R^{net}_e(\theta)-\lambda_{dd}MDD_e(\theta)-\lambda_{tail}ES_e(\theta).
\]

Mọi term dimensionless account return, coefficients là preference không mặc định1. Equal-time hoặc time-rate convention cần khóa nếu episodes dài khác nhau. Turnover/capacity penalty chỉ thêm như preference riêng; fees/slippage đã trong net return không trừ cùng cost lần hai.

**`PSR_EVIDENCE_V1`:** `v_e=PSR_e` hoặc dependence-aware evidence score đã version. Cần economic quality/risk constraints riêng; không selection chỉ vì p gần1. Undefined environment không tự là0 hoặc1.

**`LEGACY_SHARPE_UTILITY_REPLAY`:** giữ đúng công thức lịch sử để tái hiện T1/T2. Không dùng tên PSR cho Sharpe-MDD score.

Trong composite, tất cả aggregate/dispersion/fragility phải cùng channel hoặc transformed bằng reference scales được freeze trên development. Không cộng minPSR với raw Sharpe drop, dollars hay bps không conversion.

## 5.4 Họ objective 1 — Environment floor, lower-tail utility và regret

### 5.4.1 Worst-floor có ý nghĩa nhưng finite-scope

\[
J_{floor}(\theta)=\min_{e\in\mathcal E}v_e(\theta)
+\lambda_m\sum_e q_e v_e(\theta)-Pen_{activity}(\theta).
\]

`q_e` normalized predeclared environment weights. Nếu v=U thì có economic interpretation; nếu v=PSR thì là evidence-score trade-off. Không average regime Sharpes rồi gọi đó là Sharpe tài khoản tổng.

Với v=utility, `min_e U_e` bằng worst expected utility dưới mọi reweighting trên finite support `E`. Đó là limited DRO interpretation, không robustness trước unknown future regime. Nếu mandate cần ambiguity set quanh empirical weights, define rõ `Q` và solve `inf_{q∈Q} q·U`; không thêm một optimizer phức tạp mặc định.

### 5.4.2 Sửa average-regret naming

Spec cũ:

\[
J_{old}=\min_e v_e-\lambda\sum_e q_e(b_e-v_e)-Pen.
\]

Nếu b được freeze chung:

\[
J_{old}=\min_e v_e+\lambda\sum_e q_e v_e-\lambda\sum_e q_e b_e-Pen.
\]

Ranking là floor+weighted mean. Giữ replay version; canonical name nói đúng, không tuyên bố minimax regret.

True finite-panel minimax regret:

\[
Regret_e(\theta)=b_e-U_e(\theta),\qquad
\theta^*=\arg\min_\theta\max_e Regret_e(\theta).
\]

b_e do independent/reference candidate set hoặc frozen stage panel xác định. Nếu panel mở rộng làm b thay đổi, phải tạo reference revision và recompute all scores cùng stage; không đưa moving objectives vào Optuna rồi so trials như cùng objective.

Regret thấp chỉ nghĩa gần benchmark; nếu mọi candidates lỗ, regret thấp không phải edge. Include cash/approved incumbent comparator ở đúng economics khi mandate cho phép, không force best-of-bad.

### 5.4.3 Lower-tail mean khác quantile

Với utilities U và discrete scenario weights q, define:

\[
LTM_\alpha(U)=\frac1\alpha\int_0^\alpha Q_U(p)\,dp,\quad0<\alpha\le1.
\]

Implementation sort U tăng, lấy đúng alpha probability mass, fractional last atom. Với losses L, `ES_q(L)=(1/(1-q))∫_q^1 Q_L(p)dp`. Hai conventions không tráo [S8].

Oracle: `[0.01,0.90,0.91,0.92]`, equal weights → Q25(linear)=0.6775 nhưng LTM25=0.01. K=4, alpha25% → LTM=min; report redundancy nếu objective cũng có min. Alpha1 → weighted mean.

Selector-tail prototype:

\[
J_{tail}(\theta)=a\min_e v_e+bLTM_\alpha(v)-cMAD_q(v)-Pen_{activity}.
\]

a,b,c,alpha frozen in plan; legacy 1/0.5/0.2 có thể là comparison recipe, không universal defaults. Weighted MAD/median tie convention explicit. `full_dro_cvar` phải báo `tail_definition=lower_environment_utility_tail` hoặc `daily_loss_ES`; không để user hiểu nhầm.

## 5.5 Họ objective 2 — Active local robustness, schema + covariance

### 5.5.1 Neighborhood core

Tạo `N_schema` bao gồm feasible adjacent int/grid moves, signed numeric moves theo radius, category flips có meaning và joint perturbations trên coupled dimensions. Candidate-specific adaptive covariance chỉ bổ sung:

\[
\mathcal N(\theta)=\mathcal N_{schema}(\theta)\cup\mathcal N_{cov}(\theta).
\]

Tối thiểu report dimensions/groups được probe, uncovered directions, effective distances, clipped/projected duplicates. Một tranche8 probes không mặc nhiên phủ12 active dimensions.

### 5.5.2 Covariance regularization và interpretation

Ước lượng covariance trong normalized active continuous subspace của **một basin đủ support**, không global multimodal pool:

\[
\Sigma_{reg}=(1-\rho)\hat\Sigma+\rho D+\tau^2I.
\]

rho/tau/eigen floors chọn development, không OOS. Eigenvalue floor không thay schema probes; need both. Sparse/singular cloud hoặc ít samples → fallback schema-only. Không gọi sample covariance là Hessian. Nếu optional Hessian finite differences có thật, report riêng và vẫn cần function evaluations.

\[
\delta_j=\epsilon V\Lambda_{reg}^{1/2}u_j
\]

chỉ tạo proposals; feasibility, quantization và minimal/effective radius được validate. Symmetric raw proposal không đảm bảo symmetric feasible perturbation gần boundary; disclose.

### 5.5.3 Downside và objective

\[
F_{max}(\theta)=\max_{u\in\mathcal N(\theta)}[f(\theta)-f(u)]_+,
\qquad J_{local}=f(\theta)-\gamma F_{max}(\theta)-Pen_{activity}.
\]

f là same base aggregate/channel cho center và neighbors. gamma1 → exact min utility trên center+probes đã chạy. Đây là empirical local worst-case, không bound cho toàn ball hoặc unseen environment.

Nếu v=PSR, use f in PSR units. Nếu f=return utility, fragility cũng return utility. Missing/runtime-invalid probes làm evidence incomplete, không xóa xong lấy max phần còn lại như full validation. Feasible-but-economic-loss phải giữ.

### 5.5.4 Covariance blind-spot oracle

`f(x,y)=1-x^2-10000y^2`; observed top candidates có y=0. Covariance y=0 làm ellipse không đi theo y. Probe y=0.01 giảm1.0 utility dù covariance probes gần flat. Test bắt buộc union neighborhood phát hiện hướng đó.

SAM gốc tối ưu neural-network neighborhood loss [S7]. Mượn ý tưởng local robustness được phép, nhưng không gọi finite backtest probes là chứng minh generalization cùng SAM theorem.

### 5.5.5 Roughness normalization

Primary report absolute downside units. Optional normalized:

\[
F_{norm}=F_{max}/s_{ref},\quad s_{ref}>0
\]

với scale lấy từ fixed dev reference IQR/MAD/economic tolerance. Không dùng |f(center)| gần0. Cộng constant vào utility không được làm physical landscape đột nhiên “phẳng100 lần”. Scale/reference_id đi vào cache/selector fingerprint.

### 5.5.6 Medoid/centroid

Medoid chọn representative sau quality/local stability gates:

\[
\theta_{medoid}=\arg\min_{\theta_i\in C}\sum_jd(\theta_i,\theta_j).
\]

Nearest arithmetic centroid tối ưu một số squared-Euclidean objectives, không same mọi d. Centroid mới phải qua feasibility và actual evaluation trước selection. Giữ distinct basin IDs; không average hai basins tạo một candidate ở valley rồi deploy chưa test.

## 5.6 Họ objective 3 — Unified composite có scale/weights rõ

\[
J_{unified}(\theta)=w_1\min_e v_e+w_2\bar v_q
-w_3SD_q(v)-w_4F_{max}(\theta)-Pen_{activity}(\theta).
\]

Nếu dùng weights0.35/0.35/0.15/0.15 như Spec cũ, ghi là preregistered candidate recipe, không kết quả tối ưu. Tất cả terms cùng channel hoặc reference normalization. Tính min/std/fragility tương quan nhau; ablation phải chỉ ra added component có ý nghĩa hay chỉ double-penalize risk.

Không tune tất cả weights, thresholds, K, regimes và sampler trên same holdout. Diagnostic development chọn bounded shortlist; freeze plan trước calibration/validation.

Activity/support handling không khuyến khích churn chỉ để vượt trades floor. Có thể mandate một minimum number of opportunities, nhưng no-trade state của strategy specialist phải được diễn giải và uncertainty báo rõ. Không perverse incentives tăng fills bằng split orders để tăng score.

## 5.7 Pareto, normalization và Chebyshev

Maximize vector v_e với risk constraints. Pareto front `P` chỉ từ common admissible candidate set. Freeze utopia u*, nadir u− hoặc economic reference bounds từ development/reference panel:

\[
a_e(\theta)=\frac{u^*_e-v_e(\theta)}{u^*_e-u^-_e},\quad
\theta^*=\arg\min_{\theta\in P}
\left[\max_e w_e a_e(\theta)+\rho\sum_e w_e a_e(\theta)\right].
\]

Zero range → objective có flag non-discriminative; không divide0. Candidate ngoài frozen bounds không silently clip mọi improvement; report extrapolation và apply versioned policy. Equal weights vẫn là preference. Chebyshev là compromise rule, không unique true knee [S9].

Hypervolume dùng fixed reference, direction conventions và same normalized objective space. Same front cho mọi selectors → same hypervolume; không dùng nó để chấm selected point nào tốt. NSGA-II search là population evolutionary process khác QMC+Pareto post-selection [S11].

## 5.8 Statistical inference và phép kiểm “có ý nghĩa kinh tế không?”

Đăng ký primary target, effect margin và inference family trước targeted confirmation. Các secondary metrics vẫn báo đủ, nhưng không chọn metric thắng sau khi xem rồi gọi primary.

Paired contrast giữa recipes trên common daily calendar:

\[
\Delta_t=r^{new}_t-r^{base}_t.
\]

Dùng blocks giữ serial dependence và common shocks khi nhiều alpha/symbol. Chọn block policy từ development/holding diagnostics; không seed-shopping. Sample-average Sharpe differences cần recompute Sharpe mỗi bootstrap sample, không average per-day Sharpes.

Một CI của selected fixed configs không tự bao gồm uncertainty của sampler/recipe selection. Muốn đánh giá whole process cần outer repeated origins hoặc resample/replay appropriate selection layer; không bootstrap mỗi winner curve rồi tuyên bố router validated.

Minimum economic improvement delta phải cùng units với endpoint. Cost margin dùng actual account turnover/allocation; 0.1 account notional khác full-account notional. Không hạ delta hậu nghiệm để phương pháp thắng. Business hurdle độc lập với cost derivation được phép nhưng phải ghi là preference.

Outcome:

```text
INVALID / NOT_EVALUABLE
INCONCLUSIVE
NEGATIVE_WITHIN_REGISTERED_SCOPE
POSITIVE_WITHIN_REGISTERED_SCOPE
```

Không significant ≠ evidence zero. CI loại delta>0 có thể cho kết luận “không đạt mức cải thiện đã đăng ký” trong scope, không vô hiệu toàn mode/family. Multiple metrics/recipes/calibration origins có hypothesis ledger; family adjustment policy phải predeclared. PSR/DSR là diagnostics, không sửa lookahead hoặc holdout reuse.

## 5.9 Counterexamples phải nằm trong review, không chỉ theory appendix

| Giả định đáng nghi | Phản ví dụ/kiểm tra | Hành động nếu bị bác |
|---|---|---|
| Top-trial density = robust plateau | Peak hẹp được sampler ghé nhiều, bad neighbors ngoài top | Independent probes và coverage metrics |
| Nearest centroid luôn là medoid | Points0,1,2,3,100 | Version distance/representative; evaluate centroid |
| PSR xóa sample imbalance | Same SR, N khác → evidence khác đúng chủ đích | Giữ uncertainty và economic utility riêng |
| Scale returns là volatility stress cho Sharpe | SR(ar)=SR(r) khi a>0, rf0 | Stress market/strategy/execution phù hợp hoặc dùng risk metrics |
| Mean regret là minimax | Algebra min+mean−constant | Đổi tên hoặc implement max regret |
| Q25 là CVaR | Lower-tail mass khác quantile interpolation | LTM/ES contract có fractional atom |
| Covariance ellipse phát hiện mọi fragility | Narrow transverse direction absent trong top cloud | Schema floor+union probes |
| Rank correlation thấp loại robust candidate | Stable best, all lower ranks reverse | Near-optimal set và candidate-level tests |
| Many backtests = many independent samples | Same market path × candidate variants | Episode/common-shock uncertainty |
| Fixed params không thể adapt | A-HMA effective-length recursion | Profile internal adaptation thay nhãn theo family |

---
<a id="chapter-6"></a>
# Chương 6 — Bốn selectors và lifecycle diagnostics → calibration

## 6.1 Common selector interface

Selector chỉ nhận verified typed panel/reference metrics, parameter schema, plan/preferences và evidence refs. Không tự gọi data APIs, tự synthesize fills hoặc xem holdout trên disk.

Proposed pure interface, map vào registry thực:

```text
select(panel, candidates, selection_plan, diagnostic_dossier_ref)
    → SelectionDecision
```

Output gồm requested/resolved selector, formula_version, compared candidate IDs, per-component scores, constraints/statuses, normalization/ref benchmark IDs, pre/post incumbent guard, chosen candidate/NO_SELECTION, tie-break và evidence refs.

Không đủ input cho formula → preflight reject hoặc explicit research fallback đã đăng ký; không đổi thuật toán im lặng. Mọi fallback có reason, source algorithm và impact on claim.

## 6.2 `full_dro_cvar`

Giữ slot, nhưng có versions phân biệt:

- `legacy_spec_1_1_quantile`: replay minPSR +0.5Q25−0.2MAD khi inputs đủ và xác nhận đây là historical formula. Tên hiển thị là quantile-floor heuristic, không CVaR.
- `environment_lower_tail_v2`: min + lower-tail mean − weighted dispersion, channel PSR/economic utility theo plan; true tail contract.
- `finite_panel_minimax_regret_v1`: chỉ khi explicit chọn max-regret formulation, không tự bật vì slot có chữ DRO.

Feasibility precedes ranking; risk-failing valid candidates vẫn ở panel để report, không chọn nếu mandate cấm. Undefined PSR không nhất thiết cả alpha invalid: dossier có thể đề xuất economic channel khi đủ daily/campaign path evidence, nhưng phải freeze trước calibration. Không drop unknown environment để tăng minimum.

Alpha HASH là regression/challenger ưu tiên từ T2, không route hardcoded `if alpha==HASH`.

## 6.3 `full_sam_basin`

Stages: broad candidate discovery → basin/center identification → fixed schema+covariance probes → local objective → evaluate actual representative → local validation tranche.

Nếu gamma1 và no other penalty, output phải reconcile với min utility trên center+evaluated neighbors. Stochastic execution scenarios dùng common exogenous randomness khi phù hợp và candidate-independent seeds; không ép order-dependent draw order tạo false parity.

Covariance fit thiếu support → schema-only explicit fallback, không reject mọi alpha và không fake Hessian. Multiple basins có local fits; medoid được chọn trong valid evaluated set. Centroid/corrected params là candidate mới, có budget count riêng.

VWAP là targeted case cần kiểm conditional branches và HTF warmup. Không bỏ amendments/stops để tạo flat signal surface giả.

## 6.4 `full_pareto_chebyshev`

Bộ chọn dùng verified candidate/environment matrix, non-dominated set và frozen preferences. Báo đầy đủ Pareto rows, normalized objective values, utopia/nadir reference, contribution và alternatives gần winner.

Không cần NSGA-II để dùng selector này. Nếu chạy NSGA-II sampler, report đó là end-to-end multiobjective search experiment riêng và audit population/generation/budget. Existing QMC panel không được relabel như NSGA-II.

Hypervolume là panel/sampler diagnostic; selected candidate dùng compromise utility/risk và stability metrics. Thêm một candidate outlier không được silently rescale preferences của previous calibration result; create analysis revision nếu reference thật sự đổi.

## 6.5 `full_alpha_adaptive_invariant`

Giữ ý tưởng meta-selector, sửa authority:

1. Đọc dossier hợp lệ với same alpha/economics/schema/scope.
2. Lấy ranked shortlist theo measured battery effects và support.
3. Resolve explicit researcher choice hoặc validated deterministic routing policy.
4. Freeze `CalibrationPlan` trước search chính thức.
5. Không reroute dựa kết quả của holdout hoặc chọn recipe thắng sau final replay rồi gắn freeze giả.

Default maturity V1: **advisory-first**, có override reason và `routing_evidence_status`. Auto route chỉ cho shapes đã có whole-procedure evidence. Nếu chưa clear winner, dùng declared safe legacy/anchor recipe hoặc yêu cầu researcher decision; không lấy radar max từ số bịa.

Full-pipeline recipe chooser là model selection; validation phải include diagnostics, sampler/objective/selector choices. Không huấn luyện một classifier từ bốn labels “HASH:DRO, VWAP:SAM, SC:Pareto, HMA:M4”.

## 6.6 Incumbent, no-trade và rejection

Incumbent chịu same objective/components/probes/constraints như challengers. Legacy primary floor giữ reproduction version; không silently đảo robust winner về raw Sharpe peak ở cuối mà report vẫn nói selected by robustness.

Mandate có thể cho phép cash/flat fallback. `NO_SUPPORTED_CONFIGURATION` là output hợp lệ, không force best numerical score khi mọi candidates risk-fail. Parameter candidate selection khác quyền deploy live; không tự create orders/accounts trong phase calibration.

## 6.7 Exact freezing points

```text
DiagnosticStudy registered
    → executed panels / diagnostic revision
    → AdvisoryDossier committed
    → CalibrationPlan sealed
    → Search trials / optional stage revisions allowed by plan
    → CandidateSet frozen
    → SelectionDecision sealed
    → SelectedParams digest frozen
    → Validation access unlocked if a legitimate untouched scope exists
    → CalibrationResult + independent validation references
```

Dossier cần invalidation khi alpha logic, execution timing/cost, effective schema, data scope hoặc statistical contract đổi. Một metadata/report text change không bắt chạy lại economic simulations nếu dependencies không đổi.

Mode5 result vẫn `none_full_sample_calibration`. Tồn tại validation child run không biến training metrics thành OOS. Nếu refit full data sau khi thấy validation, params mới có lineage khác; không thừa kế “đúng vector đã qua holdout”.

---

<a id="chapter-7"></a>
# Chương 7 — Architecture, evidence contracts và triển khai 12 phases

## 7.1 Module layout: mở rộng layer nghiên cứu, không tạo financial kernel

Tree dưới đây là target organization tương đương, không bắt tạo duplicate modules nếu source đã có:

```text
existing_lab_or_quantbt_extension/
  alpha_profiling/
    contracts.py                # DiagnosticStudy/Panel/Dossier/CalibrationPlan
    inventory.py                # source/data/evidence reconciliation
    mechanics.py                # derive profiles from QuantBT events
    parameter_geometry.py       # effective schema/branches/dependent transforms
    panel_plan.py               # required computations, cache and budget
    environment_views.py        # anchors and rolling-state views
    sensitivity.py              # SALib/design integration or labeled screening
    neighborhoods.py            # schema + covariance designs
    invariance.py               # ranks, near-optimal sets, transfer/support
    battery.py                  # five registered hypotheses
    dossier.py                  # evidence-backed advisory; no fake winners
  mode5_extended/
    metrics_contract.py         # reuse canonical metrics where available
    evidence_scores.py          # PSR/HAC/tail references or wrappers
    objectives.py               # three objective families, formula registry
    selectors.py                # four versioned selector slots
    integration.py              # thin adapter to actual Mode5/WFO
  tests/mode5_upgrade/
  scripts/                      # extend current runner/CLI
  evidence/mode5_upgrade_v1/
```

Sampler factory, execution manager, order/account code, data loader, trial store và report writer đang có phải được reuse. Không tạo `mode5_extended/samplers.py` chứa clone TPE/CMA/QMC khi registry Mode4 đã đủ. Wrapper nếu cần chỉ normalize/record configuration.

Python cho alpha features, model selection orchestration và evidence analysis. Rust-first cho supported simulation và pure numeric hot reducers khi đúng dữ liệu và profile chứng minh lợi ích. NumPy/Numba fallback được giữ minh bạch; không có phase bắt viết lại indicator strategy trong Rust.

## 7.2 Computation/output plan và cache

Plan lấy union của inputs cần cho objective, constraints, five-axis profile, battery và audit. Không trả scalar score rồi sau đó chạy cùng simulation ba lần để lấy returns/campaigns/ES.

Ba key layers:

```text
ExecutionKey:
  alpha code + effective params + market snapshot + initial state + timing
  + instrument/cost/funding/account/terminal contract + scenario seed

AnalysisKey:
  ExecutionKey + environment membership/view + metric/statistical contract
  + normalization/reference version

SelectionKey:
  AnalysisKeys + candidate universe + objective/selector/preferences
  + diagnostic/calibration plan + access-rights scope
```

Data-role authorization là gate ngoài mathematical identity: matching hash không cho phép dùng holdout-cached outcomes để chọn recipe. Selection replay qua current cutoff chỉ thấy artifacts đủ maturity trước cutoff đó.

Mỗi trial có record ngay cả khi reuse evaluation. Failed/pruned/cancelled không đổi thành COMPLETE −1e9. Candidate infeasible có status/constraints; runtime failure không là economic bad sample.

## 7.3 Resource plan và tốc độ không làm hỏng methodology

Default procedure:

1. Read/reanalyze current caches before any new market execution.
2. Execute mathematical/code fixtures dưới vài giây/phút.
3. Run một short but eventful real-alpha binding pilot/route, có max wall-time.
4. Ước lượng total work bằng `measured seconds per candidate×environment×bars` và report trước job lớn.
5. Shard theo candidates/alpha/environment, bounded workers, deterministic result order.
6. Reuse prepared market/indicators phụ thuộc params, không materialize full DataFrame/report mỗi trial.
7. Retain required daily/campaign evidence; chỉ full dense order trace cho selected/regression/stress cases khi retention contract cho phép.

Runtime modes:

| Mức | Mục tiêu | Ngân sách proposal, phải calibrate bằng pilot |
|---|---|---|
| `AUDIT_ONLY` | Manifest/math/reanalysis từ cache | Không market rerun |
| `TARGETED_VERIFY` | Nghi vấn còn mở | Tranche tối đa128 missing candidate-environment evaluations theo §7.5 |
| `PROFILE_STANDARD` | Dossier cho alpha mới/scope đủ rộng |128 unique feasible configs, nâng256 khi uncertainty/coverage yêu cầu |
| `PROFILE_DEEP` | Sensitivity structured/rare-event extension | Budget riêng được chấp thuận; không silently mở hàng nghìn runs |
| `CALIBRATION` | Mode5 search theo plan đã freeze | Trial budget từ profiling và mandate, không global unlimited |

128 raw trials không bảo đảm128 effective configs. Saltelli baseN khác total model evaluations. Report both.

Mặc định test CI không chứa full-year × many-sampler sweeps. New research jobs có `--plan`/dry-run equivalent, no-overwrite outputs, cancellation và memory caps. Một shard nghiên cứu mục tiêu không quá khoảng10–15 phút sau measurement; đây là scheduling target, không lời hứa runtime. Nếu full statistically adequate study lâu, chia shards và resume; không rút dữ liệu/trials âm thầm rồi claim cùng bằng chứng.

Parallelize independent evaluations. Không parallel thời gian của account state, carried folds hoặc adaptive tell order trái contract. `python_processes × rust_threads × BLAS_threads` nằm tổng budget. Không yêu cầu port objective sang Rust trước khi biết nó là bottleneck.

## 7.4 Core evidence schemas

### `AlphaDiagnosticDossierV2`

```json
{
  "schema": "quantbt.alpha_diagnostic_dossier.v2",
  "status": "PLANNED",
  "dossier_id": null,
  "alpha_identity": null,
  "study_id": null,
  "economic_contract_digest": null,
  "parameter_schema_digest": null,
  "data_role": "diagnostic_development",
  "validity": {"technical": "NOT_RUN", "coverage": "NOT_RUN", "replay": "NOT_RUN"},
  "matrices": {},
  "axes": {},
  "batteries": {},
  "recommendations": [],
  "mode_advisory": "UNASSESSED",
  "calibration_plan_proposal": null,
  "independent_validation_refs": [],
  "unresolved_hypotheses": [],
  "compute_bill": {},
  "provenance": {}
}
```

Đây là schema sketch, chưa có PASS/score bịa. Dossier thực phải validate refs/row counts, raw numbers, units và support. Schema field chưa đo phải null+reason, không fake0 hoặc100.

### `CalibrationPlanV1`

```text
plan_id + revision + sealed_at + allowed_cutoff
alpha/data/economic/schema identities
dossier_id + diagnostic_revision
mode_id=mode_5_full_robust
sampler_spec + actual fallback policy + seeds + schedule_contract
objective_id/version + channel + coefficients + reference sets
selector_id/version + tie-break + incumbent policy
search domain / fixed/inactive/dependent mappings
required environment views + metric/retention contracts
local probe design / covariance stage boundaries / query budgets
constraints / support policy / failure handling
reuse authorization / maturity / contamination status
validation plan / deployment horizon / no-auto-deploy
```

### Mandatory ledgers

`study_registry`, `trial_ledger`, `evaluation_ledger`, `parameter_activity`, `candidate_environment_panel`, `neighborhood_design`, `neighbor_metrics`, `environment_overlap`, `recipe_comparison`, `selection_decisions`, `data_access_log`, `compute_log`, `claim_report`.

Arrow/Parquet hoặc existing SoA cho bảng lớn; JSON/JSONL cho metadata/decisions. Không duplicate environment manifests ở mỗi row. Full trial ledger phải reconcile Optuna store dù only compact financial retention. Invalid samples/negative outcomes không bị bỏ khỏi count.

## 7.5 Targeted tests bốn alpha: không mặc định chạy lại T1/T2

### T0 — Artifact/source reconciliation, zero new backtests

Generate corrected T1/T2 tables từ JSON; source hashes; unique params; actual cache inventory; historical labels/formula map; no PSR fabricated from Sharpe/fills. Map bốn alpha canonical changes với runner đã dùng.

### T1 — Contract fixtures và mathematical counterexamples

Run selected helpers, effect/feasibility probes, formula oracles, route/timing/fee/metric fixtures trên synthetic market qua QuantBT khi financial logic cần. Custom mathematical array calculations chỉ test statistics/geometry, không backtest account.

### T2 — Retrieve full cached panels và paths

Tìm full100-trial samples, returns, campaigns trên server. Verify identity/count. Nếu đủ, chạy selector-only, LORO panel diagnostic, sensitivity screens và PSR/tail reanalysis mà không new execution.

### T3 — Bounded missing-probe tranche

Proposal:2 centers/alpha ×8 unique new probes/center ×2 preselected **development** environments ×4 alphas = tối đa128 missing execution cells. Dedup/cache hits giảm work thực. Centers có thể lấy historical winners để debug cơ chế nhưng phải gắn `post_selected_diagnostic_fixture`; không dùng chúng làm unbiased sampler test.

Choose envs theo registered development questions (vd max disagreement, weak risk support) trước khi xem new probe results. Không dùng 2024 winner để chọn môi trường confirmation. Tranche này giải quyết local hypotheses, không cấp broad landscape certificate nếu active dimensions chưa phủ.

### T4 — Chỉ mở rộng khi có lý do kiểm chứng

Examples: covariance blind axis còn uncovered; VWAP warmup thiếu; HASH chưa có multi-hit/partial close; HMA clamp chưa được exercise. Mỗi extension có expected informational gain, budget và stop rule. Không thêm một sweep lớn để “chắc hơn” mà không nói câu hỏi.

## 7.6 Hypothesis register về economic meaning

| ID | Giả thuyết | Kiểm tra thực | Bằng chứng ủng hộ | Bằng chứng bác/không đủ |
|---|---|---|---|---|
| EH-01 | Floor-aware selection giảm thiệt hại ở weak environments | Shared panel, same normalized utility, diagnostic held splits; candidate fixed | Better net lower-tail utility, risk acceptable | Chỉ giảm exposure, estimates không ổn hoặc wide CI |
| EH-02 | Local robustness tránh sampler-density trap | Equal centers/probes, schema+c covariance union, held probe seeds | Lower downside with adequate center utility | Flat-negative, probe-dependent hoặc missing directions |
| EH-03 | Pareto compromise hữu ích hơn scalar peak | Same panel, predeclared preferences, held splits | Better mandate trade-off/transfer | Reference/weights changes quyết định hết hoặc no clear winner |
| EH-04 | PSR cải thiện evidence ranking chứ không chỉ sample-size preference | Raw SR vs PSR với exact frequency; economic/uncertainty reports | Reliable threshold coverage hơn trên controls, quality không collapse | Annualization bug, saturation, unsupported moments |
| EH-05 | QMC/TPE/CMA recipe khác nhau có economic consequence | Same objective/feasibility/work, small paired seed extension khi cần | Consistent performance/coverage trade-off | One-seed winner hoặc fallback explains difference |
| EH-06 | HMA `min_length` ít tác động chỉ trong tested regime | Clamp-active/inactive paths, coupled probes, cached market cases | Context-dependent effect measured | Không được suy structurally dead từ zero sample effect |
| EH-07 | VWAP SAM gain đến từ local stability | Same active branch, warmup, economics, neighbor panel | Advantage survives branch/warmup control | Gain do missing amendments hoặc different scored period |
| EH-08 | HASH tail/profile không bị partial-fill counting làm méo | Campaign aggregation + actual rungs/fees | Tail/risk story ổn theo net campaign/account | Fill-count skew bị đổi nghĩa hoặc residual mishandled |
| EH-09 | SC gains không chỉ một market-long episode | Daily/exposure/campaign contribution, net baseline control | Contribution tồn tại ngoài single-event exposure explanation | Sparse opportunities; no broad inference |
| EH-10 | New recipe giảm forward decay hữu ích | Repeated fixed-parameter origins hoặc valid cached paired windows | Forward utility tốt hơn, decay/support rõ | Chỉ IS giảm hoặc cùng reviewed holdout |
| EH-11 | Five-axis router chọn recipe hữu ích | Hold out whole decision episodes/alpha domains khi đủ scope | Whole-process validation improves mandate | Four-alpha lookup, radar rescale hoặc winner-picking |
| EH-12 | Cache/vectorization giữ đúng evidence với tốc độ cao | cold/warm, cached/fresh, score/retained paths, fixed intents parity | Same economics, reports reproducible, work giảm | Stale role/seed/warmup cache hoặc metrics bị mất |

Các EH là hypotheses, không prerequisites bắt buộc phải đúng. Technical gate bắt buộc test capable và truthful; economic gate ghi positive/negative/inconclusive theo registered scope.

## 7.7 Phase map và dependencies

```text
M5-01 Baseline, errata, isolation, contract inventory
  → M5-02 Four-alpha economic admission / actual route
  → M5-03 Metric, units, PSR, uncertainty and math oracles
  → M5-04 Diagnostic panel planner, cache and provenance
  → M5-05 Dual environments and chronological data roles
  → M5-06 Parameter geometry, sensitivity and active neighborhoods
  → M5-07 Versioned objective/selector implementations (reference first)
  → M5-08 Five empirical batteries + targeted four-alpha verification
  → M5-09 Dossier/advisory + CalibrationPlan seal
  → M5-10 Public Mode5 integration and sampler/runtime reuse
  → M5-11 Targeted formal calibration/validation and economic inference
  → M5-12 Qualification, docs, Mode4 regression and handoff
```

M5-05 và một phần geometry M5-06 có thể phát triển song song sau M5-04, nhưng exit M5-06 cần environments/metrics hợp lệ. Pure reference objective tests ở M5-03/06 được đưa vào canonical implementation M5-07, không giữ ba bản formula khác nhau. M5-08 dùng chính implementations M5-07 để chạy diagnostic mini-experiments; **formal Mode5 tuning bắt đầu sau dossier M5-09**.

Mỗi phase có report trước khi advance. Existing work mapped `VERIFIED_EXISTING` khi có public-path evidence. Tất cả 12 phase là scope mới của Mode5 upgrade, không đổi số hay status phases Mode4 đã hoàn tất.

---
## Phase M5-01 — Baseline, errata và research contract freeze

**Mục tiêu:** một source/evidence identity đáng tin, không tái diễn diễn giải sai từ tables hoặc code version cũ.  
**Phụ thuộc:** có quyền đọc input archives, actual Mode4/5 checkout và data-cache manifests.  
**Không làm:** market rerun đại trà, sửa economic kernel, publish package.

### Work packages

- **M501.01 — Pin và protect.** Lưu SHA archives, extracted members, actual repo SHA/dirty state, wheel/core/native/import origins, Python/Rust/Optuna versions và locks. Tạo writable workspace mới; originals/core production read-only. Không import bytecode/cache từ ZIP.
- **M501.02 — Reconcile evidence.** Generate T1/T2 tables và unique-parameter map từ JSON. So Spec/report/master artifacts; tạo errata có old value/new value/source pointer. Giữ historical claims nhưng bổ sung scope/status không đúng.
- **M501.03 — Map current source.** Trace public Mode5 và inherited sampler/evaluator/selector/metrics/retention. Mỗi requirement có source symbol, test và consumer. Không cần xem lại toàn repo performance nếu interface đã được certify.
- **M501.04 — Data-role registry.** Mark reviewed 2024 exploratory; pin calibration/development/diagnostic validation scope. Fullset presets làm reference only. Ghi unknown contamination, không tự invent untouched window.
- **M501.05 — Register study/mandate.** Define questions EH-01…12, primary outcomes, economic/risk constraints, runtime budgets, baseline configs và no-auto-deploy. Thông số còn chưa biết là unresolved precondition, không âm thầm fill0.
- **M501.06 — Test harness và report.** `.py` runners dùng current interpreter/env, bỏ hardcoded external venv paths. Run archive/schema/math syntax checks và document source differences trước khi chọn tests cần market replay.

### Economics và tests

Nhóm M5T-001…010. Câu hỏi có thể trả lời: tables có đúng records không; evidence có đủ để reanalyze metric nào; benchmark source có tương thích canonical alphas mới không. Chưa đánh giá recipe profitability.

### Deliverables và exit

`baseline_manifest.json`, `evidence_errata.json`, `current_api_binding_map.json`, `artifact_reuse_plan.json`, `study_registration.json`, `report.md/json`. Exit khi mọi inputs mandatory có identity/role, discrepancies có disposition, protected paths unchanged. Missing full panels → plan targeted recovery, không tự claim source absent toàn server.

**Báo cáo bắt buộc:** nêu riêng confirmed artifact discrepancy, source observation, hypothesis và unverified runtime; planned vs avoided backtest count.  
**Rollback:** workspace/research revisions mới; không thay originals.

## Phase M5-02 — Four-alpha economics admission và actual QuantBT route

**Mục tiêu:** diagnostics đo đúng alpha và đúng financial outcome.  
**Phụ thuộc:** M5-01.  
**Không làm:** redesign strategy, thêm short cho SC, collapse HASH ladder, bỏ VWAP amendments hoặc thay internal HMA.

### Work packages

- **M502.01 — Alpha binding contracts.** Map constructors/parameter schemas/effective casts, fills callbacks, indicators và execution capability. Source fixes cũ đã có (HMA aliases) → verified-existing, không reintroduce lỗi để test.
- **M502.02 — SC/HMA fixtures.** Verify SC integer coeff/long-flat/volume branch/scalar-vect parity. HMA inactive vs active knobs, canonical SL enum, ATR/minmax coupling, internal adaptation và gap behavior.
- **M502.03 — VWAP/HASH fixtures.** HTF closed-bucket mapping, parameter-dependent warmup, time-stop branch và amendments; ladder fractions/rounding/residual/cooldown/campaign aggregation.
- **M502.04 — Financial golden cases.** QuantBT real engine on small deterministic bars: one-way fee binding, next eligible fill, reversal/partial close, unrealized equity, protective priority, terminal contract. Reference tests phải check full relevant trace, không chỉ final equity/bar sets.
- **M502.05 — Actual runner witness.** Trace each benchmark/profile route to QuantBT. Record requested/resolved endpoint/backend. Quarantine legacy fixed-point fixture from certification path nếu không actual feedback; nếu production runner dùng nó, repair trong lab adapter bằng existing engine callbacks hoặc block capability cụ thể.
- **M502.06 — Short real-data pilot.** Một representative config/alpha trên một hoặc hai existing eventful development windows; use cache first. Common score interval với đủ warmup. Four rows phải valid hoặc blocked-with-reason, không loại alpha khỏi denominator vì khó.

### Economics và tests

M5T-011…020, EH-06…09. Test payoff preservation, effective domain và actual execution. Chi phí higher fee không nhất thiết monotonic whole-strategy PnL với equity-reactive decisions; check exact fixed-fill fee arithmetic riêng và actual dynamic result riêng.

### Deliverables và exit

`alpha_admission_matrix`, per-alpha `effective_schema`, `warmup_contract`, `route_witness`, small real pilot paths/campaigns, financial reconciliation. Exit khi supported bốn alpha primary route pass semantics; blocked alpha có required fix hoặc maintainer-approved narrowed scope. Không gọi full bốn alpha complete khi một alpha chưa thật chạy.

**Báo cáo:** distinguish synthetic engine vs actual-market pilot, old/new alpha identity, repair-induced PnL changes vs methodology changes.  
**Rollback:** adapters via versions/config; existing core untouched; invalid old fixture giữ diagnostic-only.

## Phase M5-03 — Metrics, PSR, units, tail và uncertainty primitives

**Mục tiêu:** số liệu trong dossier đúng nghĩa và không có false confidence do units.  
**Phụ thuộc:** M5-02 canonical return/campaign/event streams.  
**Không làm:** tune objective coefficients theo 2024.

### Work packages

- **M503.01 — Metric dictionary.** Map package raw metrics và canonical derived fields; fix unit/name ambiguities, positive MDD, PF grouping, first observation và day boundaries.
- **M503.02 — PSR reference.** Implement/reuse classical plug-in contract, checks finite/moments/N/reference frequency; keep expected numerical fixtures. Invalid không thành favorable score.
- **M503.03 — Dependence evidence.** Reuse block/bootstrap hoặc supported HAC implementation; name estimator version/bandwidth. Report moment uncertainty. Không pretend N_eff heuristic là same PSR formula.
- **M503.04 — Tail and regret primitives.** Implement weighted lower-tail mass, ES loss convention, median/MAD/zero support, frozen reference regret, raw component retention.
- **M503.05 — Economics units.** Fee/notional/account allocation, bps/decimal/percent, episode boundary PnL and compounding, risk-free scaling, cost margin. Oracle cases O01…O22 và complete assertions.
- **M503.06 — Reanalyze existing paths.** Recover cached returns/campaigns nếu có; calculate only supported new fields. Missing paths → `REPLAY_REQUIRED`, không fabricate skew/PSR từ summary.

### Economics và tests

M5T-021…030, EH-04/EH-08. Technical objective là phát hiện annualized-PSR bug, quantile-vs-tail error và PF/fill confusion. Không có evidence PSR “thắng” thị trường chỉ từ formula pass.

### Deliverables và exit

`metric_contract_registry`, reference functions/tests, `metric_reconciliation`, `moment_support_report`, `artifact_metric_availability`, updated panels. Exit mọi candidate metrics reproducible từ source data streams đủ và null reasons complete.

**Báo cáo:** estimation assumptions, sample frequency, N vs campaigns, where results unchanged/changed, exact numerical tolerance.  
**Rollback:** new metric contracts opt-in, old names replay preserved.

## Phase M5-04 — Diagnostic panel planner, cache và provenance

**Mục tiêu:** một evaluation phục vụ nhiều diagnostics, giữ transparency mà không full rerun mọi lúc.  
**Phụ thuộc:** M5-01…03.  
**Không làm:** dựng pool/cache/event engine mới nếu Mode4 đã có.

### Work packages

- **M504.01 — Required-computation DAG.** Union metrics/returns/campaign/context needs từ five axes/battery; plan một execution output đủ dùng. Map scalar-only limitations trước chạy.
- **M504.02 — Candidate/env schemas.** Implement row statuses, raw/effective identity, trial refs, common scored intervals và versioned contracts.
- **M504.03 — Cache authorization.** Three-layer keys §7.2; role frontier/seed/warmup/terminal/economic mismatches invalidate. Matching hash không vượt data-access rule.
- **M504.04 — Recover historical matrices.** Search local cache via manifests, import compatible rows và label source; record exact number rows reused/recomputed/missing. No winner-only substitute for full panel.
- **M504.05 — Bounded executor integration.** Reuse native prepared runtime; batch independent tasks; no report per trial. Share immutable market, cache strategy features only under correct params/data cutoff; retain actual counters.
- **M504.06 — Audit append/flush.** Trial ledger all statuses, typed columnar rows, crash-safe chunks/references. Final success sau required audit flush; no O(n²) full-history rewrite mỗi trial.

### Economics và tests

M5T-031…040, EH-12. Cached/fresh, worker topology và score/audit streams giữ same economics. Returned trial history không bị dedup mất records.

### Deliverables và exit

`panel_plan`, `cache_decisions`, `candidate_environment_panel`, `trial/evaluation ledgers`, resource profile, recovery recipe. Exit same repeated query không simulation lại nếu compatible; changed costs/alpha/cutoff không stale hit. Performance đo same work, không claim cache-hit speed là cold-run speed.

**Báo cáo:** saved unique executions, bytes, preparation/strategy/kernel/metrics/report timings, missing-data reasons, cold/warm/cache outcomes.  
**Rollback:** disable new cache/planner optimizations về evaluator cũ đúng contract; evidence vẫn readable.

## Phase M5-05 — Dual environments và chronological information frontier

**Mục tiêu:** anchors+rolling views bao quát điều kiện thị trường mà không fake OOS hoặc double-count evidence.  
**Phụ thuộc:** M5-04.  
**Không làm:** active regime-based switching vào Mode5 deployment.

### Work packages

- **M505.01 — Anchor manifests.** Import exact D1/D2/D3 windows, warmup/score ranges, lifecycle contracts. Separate generic labels với actual interval; scored mismatch phải hiện.
- **M505.02 — Continuous path attribution.** Extract per-day/campaign summaries từ actual QuantBT path; no price splice, no reset account at regime label.
- **M505.03 — Rolling endogenous views.** Fit train-only scaler/thresholds/provider tại mỗi required origin; record filtered vs retrospective diagnostic role. Reuse regime package available.
- **M505.04 — Overlap/support matrix.** Shared-date weights, exposures, missingness, episode recurrence, cold-start dependence và dual-family scores. Không biến một ngày thành nhiều independent observations.
- **M505.05 — Inner/outer plans.** Chronological diagnostic selection and held checks; true LORO separate from future forecasting. Preprocessing fit scopes align every split.
- **M505.06 — Mutation/replay tests.** Change future suffix, unpublished observations, thresholds or namespace: earlier eligible labels/selections unchanged under causal contract. Descriptive calibration labels có thể đổi khi calibration dataset đổi, nhưng phải version lại.

### Economics và tests

M5T-041…050. Test market regimes là evaluation contexts chứ không magic labels. Economic episode utilities và same-account attribution reconcile với full path; anchor durations không bias annualization.

### Deliverables và exit

`environment_registry`, `membership_tapes`, `overlap_support_matrix`, `data_role_and_access_log`, `inner_outer_plan`, leakage tests. Exit every view có estimand rõ và no future info in historical decision claims.

**Báo cáo:** có bao nhiêu thực sự khác economic episodes, views nào chỉ retrospective, coverage không đủ ở đâu.  
**Rollback:** disable new view, retain old explicit anchor reproduction; không silently replace candidate dataset.

## Phase M5-06 — Geometry, sensitivity và active robustness probes

**Mục tiêu:** tìm hiểu không gian thật và local stability, không dùng density top trials làm proof.  
**Phụ thuộc:** M5-04/05, metric contract M5-03.  
**Không làm:** prune toàn params bằng một threshold ST cứng hoặc tự mở huge Saltelli job.

### Work packages

- **M506.01 — Effective geometry.** Schema bounds, integer/log/conditional/coupled axes, duplicate/effective semantics. Exact parameter-effect probes cho bốn alpha.
- **M506.02 — Coverage design.** Neutral QMC/space-filling samples có registered seeds; branch allocation; independent sampler/fallback rows hiện. Reuse equivalent cached evaluations hợp lệ.
- **M506.03 — Sensitivity tier.** Cheap behavioral/local screening trước; structured Saltelli/Morris extension only with explicit assumptions/budget. Metrics utility/risk/activity riêng; constant output/nulls preserve.
- **M506.04 — Active neighborhoods.** Schema probes plus local covariance proposals; minimum per-axis/group coverage, held validation directions, feasibility and duplicate maps.
- **M506.05 — Basin analysis.** Multiple basins/near-optimal centers, local quality vs downside, medoid/centroid distinction, ratio-free roughness and uncertainty.
- **M506.06 — Targeted alpha probes.** SC coeff collision; HMA clamp-active/inactive; VWAP branch/warmup; HASH RR/fraction/quantity manifold. Không chấm arithmetic clones như new economic evidence.

### Economics và tests

M5T-051…060, EH-02/EH-06…08. Positive world có broad profitable basin; counterworld flat-negative phải fail quality; covariance blind direction phải caught; structure-inactive knobs chỉ xác nhận khi code/behavior đủ.

### Deliverables và exit

`parameter_activity_matrix`, `coverage_report`, `sensitivity_design/results`, `neighbor_design`, `neighbor_metrics`, `basin_catalog`. Exit geometric evidence đúng phạm vi; unknown directions flagged, no fake full coverage. Removal of parameter là researcher decision với validation evidence, không automatic optimization trick.

**Báo cáo:** covariance support/singular flags, all bad valid neighbors, actual unique probes, range of findings qua metrics/environments.  
**Rollback:** return schema-only probes/current full schema; source strategy unchanged.

## Phase M5-07 — Canonical objectives, four selectors và formula migration

**Mục tiêu:** công thức có tên, units và tests đúng trước khi đánh giá recipes.  
**Phụ thuộc:** M5-03…06.  
**Không làm:** chính thức tuning Mode5 trước dossier; epoch values moving giữa trials.

### Work packages

- **M507.01 — Formula registry.** Define channel, references, coefficients, constraints, null rules và formula hash cho legacy/new floors, tails, local và composite.
- **M507.02 — Environment objective.** Legacy min+mean identity, true finite-panel max-regret option, weighted lower-tail fractional mass, no mean-sharpe mixture claim.
- **M507.03 — Local objective.** Same-base f for center/probes, covariance+schema union, gamma1 identity; unknown probes không filtered invisibly.
- **M507.04 — Pareto selector.** Non-dominated rows, frozen normalization, weights, zero-range policy, tie-break; distinguish front hypervolume and chosen compromise performance.
- **M507.05 — Advisory selector boundary.** `full_alpha_adaptive_invariant` đọc versioned dossier; no four-label lookup/radar-max hardcode. Reference decision function và override audit.
- **M507.06 — Migration and deterministic tests.** Explicit selector IDs/versions; old artifact reproduce old formula; reanalysis same panel with new formula creates new SelectionDecision. Pure Python oracle vs vectorized/Rust reducer khi promote numerical acceleration.

### Economics và tests

M5T-061…070. Test worst-floor all-negative không thành “edge”, regret reference frozen, one bad neighbor không bị bỏ, Pareto positive/negative examples, quantity/cost units preserved. Các contrived arrays chứng minh meaning, không method superiority trên markets.

### Deliverables và exit

`formula_registry`, selectors, component score tables, legacy-replay tests, mathematical golden outputs. Exit mọi formula deterministic, units compatible, null/tie/reference handling explicit. Method không cần profitable để technical phase pass.

**Báo cáo:** list exact formula corrections, legacy equivalence cases, behavior changes intentional và impacted artifacts.  
**Rollback:** legacy selector/version explicit; new contracts never overwrite historical results.

## Phase M5-08 — Five empirical batteries và targeted verification bốn alpha

**Mục tiêu:** dossier có evidence chạy thật đủ để tư vấn, không chỉ source labels hoặc mathematical toy.  
**Phụ thuộc:** M5-07 cùng verified panel và routes.  
**Không làm:** blanket rerun 1.200+2.096 backtests hoặc chọn recipe bằng reviewed2024.

### Work packages

- **M508.01 — Freeze comparison roster.** Five batteries B1…B5, baselines/control hypotheses và source of centers/envs; separate selector-only/sampler-only/endtoend.
- **M508.02 — Cached panel reanalysis.** Floors, Pareto/front, fixed-panel leave-out, raw decay and effective duplicates trên artifacts đủ. Mark historical summaries vs recomputed daily results.
- **M508.03 — Execute missing-probe tranche.** Chạy tối đa planned128 missing cells hoặc actual scoped budget, đủ bốn alpha statuses. Include independent held directions, notjustbestcenter.
- **M508.04 — Small seed/sampler extensions.** Khi full panels không đủ về repeatability, thêm smallest registered extension cho baseline+challenger trên development, same objective/compute. One seed vẫn report one seed, không giả distribution.
- **M508.05 — Mechanics/risk controls.** Same exposure/cost contract, warmup common, campaign grouping, terminal/execution stresses. Use QuantBT actual simulation wherever decisions depend on stress.
- **M508.06 — Counterfactual and failure analysis.** Null world/all-bad, broad-basin positive control, signed/zero metrics, state/view permutations và recipes thật sự khác selections không. Economic gains phải sống qua meaningful controls, hoặc report rival explanation.

### Economics và tests

M5T-071…080, EH-01…10. Mỗi battery có table all candidates/recipes tested, support, primary contrast và limitations. Diagnostic held splits không bị gọi clean long-term OOS khi đã dùng để chọn phương pháp.

### Deliverables và exit

`battery_results`, `four_alpha_verification_matrix`, `targeted_probe_reports`, `compute_bill`, `hypothesis_outcomes`. Exit khi battery results/support đủ để build dossier hoặc explicit insufficiency có recovery decision. Không mask một alpha failed bằng pooled average thắng.

**Báo cáo:** what was proved vs plausible, value of additional compute, covered/uncovered cases, economic contribution/risk tradeoffs và whether recommendation changes.  
**Rollback:** failed recipe not promoted; preserve evidence âm, no cleanup erase.

## Phase M5-09 — Dossier, advisory và CalibrationPlan trước tuning

**Mục tiêu:** biến diagnostics thành quyết định nghiên cứu có thể kiểm toán; giữ cockpit mandatory.  
**Phụ thuộc:** M5-08.  
**Không làm:** auto-route mọi alpha dựa radar hoặc override technical invalidity.

### Work packages

- **M509.01 — Assemble six matrices.** Validate refs/cardinality/units, source/data roles, null statuses và actual coverage. Missing mandatory layer phải visible.
- **M509.02 — Five-axis dossier.** Separate mechanics/risk facts, model uncertainty, landscape and transfer evidence; no taxonomy from names.
- **M509.03 — Recipe recommendations.** Ranked shortlist from battery with effect/support/preferences; `NO_CLEAR_WINNER`, budget considerations và alternatives. Fouralpha rules không globalize.
- **M509.04 — Radar mapping.** Raw values+reference scales+confidence bands; no synthetic score50 cho missing. Fixed normalization không theo future winner.
- **M509.05 — Freeze plan.** Researcher/validated routing picks objective/channel/sampler/selector, search ranges/constraints/probe design/data scope/budget, validation role và incumbent policy. Seal before formal tune; overrides logged.
- **M509.06 — Dossier invalidation/reuse.** Full dependency check; source/prefs-only changes mapped. Allow safe reuse; block stale data role/source/economics/parameter scope mismatch.

### Economics và tests

M5T-081…090, EH-11. Test candidate best across environments but low ranks still eligible; no significant result -> advisory uncertain; all-negative -> no false deployment permission. Routing validated separately from formulas.

### Deliverables và exit

`AlphaDiagnosticDossierV2` JSON+MD, radar source table, `CalibrationPlanV1`, decision/override log. Exit: valid dossier exists, plan sealed, no formal tuning before it; safe no-selection plan acceptable.

**Báo cáo:** exact reasons for preferred recipes, support behind each rule, what would change recommendation and which domains remain untested.  
**Rollback:** invalidate plan and return to needed diagnostic revisions; never backfill old freeze date.

## Phase M5-10 — Public Mode5 binding, inherited samplers và prepared runtime

**Mục tiêu:** toàn đường user API thực sự sử dụng diagnostics+recipe đúng, không chỉ helper.  
**Phụ thuộc:** M5-09; actual Mode4 inheritance map M5-01.  
**Không làm:** alter Mode4 meta targets, silently change Mode1–4, public publish.

### Work packages

- **M510.01 — Opt-in orchestration.** Existing Mode5 call validates dossier+sealed plan rồi resolve route. Legacy Mode5 remains behavior-preserving without new badge.
- **M510.02 — Sampler registry adapter.** Reuse TPE variants/CMA/Sobol, log supported dimensions, independent fallback, source_trials rights, search-stage sequences. No unsupported mixed distribution hidden.
- **M510.03 — Objective-to-evaluator bridge.** Real candidate simulation returns requested retention/components. Utility never written into `mean_is_sharpe`. Custom objective explicit units, cost/warmup/timing pinned.
- **M510.04 — Trial/state semantics.** Sequential vs throughput-batch distinct; pruning/reporting restored correctly, all trials statuses, duplicate evaluation refs, cancellation no false COMPLETE.
- **M510.05 — Native/performance integration.** Prepared handles/session reuse, no repeated market copy, fused pure reducers when beneficial, no NumPy/pandas reports in score hot path. Benchmark pair on same candidate matrix before adaptive sampling.
- **M510.06 — Selected replay consistency.** Score vs compact/audit same fixed candidate and financial contract; command/fill/equity/provenance reconcile. Actual requested/resolved backend and callbacks explicit.

### Economics và tests

M5T-091…100, EH-12. Installed candidate tests outside checkout, native/reference parity representative bốn alpha routes; no guarantee all strategy callbacks native. Invalid selected run cannot feed production result.

### Deliverables và exit

Public adapter patch, capability matrix, exact runnable commands, actual sampler ledger, benchmark and selected replay evidence. Exit user route performs complete sequence with plan and data roles preserved. Existing Mode4 regression pass before proceeding.

**Báo cáo:** reused vs new components, actual hotpath, cold/warm timings, no unsupported economic substitutions.  
**Rollback:** feature flag/new selector registry entries off; old APIs unchanged.

## Phase M5-11 — Formal calibration pilot, independent checks và economic inference

**Mục tiêu:** kiểm tra recipe đã freeze có economic meaning, không dùng benchmark cũ để đóng universal conclusion.  
**Phụ thuộc:** M5-10, data role verification.  
**Không làm:** yêu cầu tất cả bốn alpha thắng hoặc retune sau khi mở evaluation.

### Work packages

- **M511.01 — Select minimal pilot scope.** Use current cache/fulldevelopment runs nếu đủ; defined calibration scopes/horizons và target baseline+challenger peralpha. No arbitrary giant factorial.
- **M511.02 — Run approved calibration.** New trials follow sealed plan; count unique work and reuses. Every rejected/failed/pruned candidate retained đúng schema.
- **M511.03 — Verify fixed output.** Selected params evaluated as actual vector with same engine, not centroid assumed; complete development economic path plus stress diagnostics.
- **M511.04 — Validation roles.** Legitimate untouched forward scope available → unlock after full pipeline freeze. Không có → historical/exploratory report + prospective plan, không fake clean holdout. Multiple origins only with complete nested rights.
- **M511.05 — Paired economics/statistics.** Forward net quality+Sharpe/return/PF decay+tail/support. Costs/allocation consistent, adjusted family claims và stop rules. Test meaningful effect, notjustp<.05.
- **M511.06 — Conclude per scope.** Separate descriptive, local-stability, transfer và decision-value conclusions. If performance weak, retain negative result; assess whether failure is method, support, exposure, horizon or input error without post-hoc rescue.

### Economics và tests

M5T-101…110, EH-01…12. No rerun toàn bộ T1/T2 required if adequate evidence recovered. Missing mandatory data/runtime gate can block scientific claim while software remains technically implemented. New major tuning design requires revision; do not keep sampling until method wins.

### Deliverables và exit

`calibration_results`, `validation_runs` nếu thật có, `paired_comparisons`, `decay_panel`, `economic_claim_report`, qualified candidate audit. Exit claims match technical validity and actual information exposure. `INCONCLUSIVE` hoặc negative acceptable; proof of universal invariance forbidden.

**Báo cáo:** initial question, actual answer, plausible mechanisms versus tested ones, remaining uncertainty, what additional targeted data would resolve it.  
**Rollback:** no deploy by default; keep incumbents/legacy configs independently from research outputs.

## Phase M5-12 — Qualification, docs, reproducibility và handoff

**Mục tiêu:** guide/spec/source/docs/results nhất quán, có thể dùng package như consumer và review scientific evidence.  
**Phụ thuộc:** M5-01…11 có disposition hợp lệ.  
**Không làm:** automatic merge/main promotion, publish package, trade live hoặc xóa independent oracle.

### Work packages

- **M512.01 — Full required regression.** Mode1–4 semantic invariants, Mode4 sampler/meta opt-in, old Mode5 replay and new diagnostics-first path; affected shared reducers across endpoints.
- **M512.02 — Artifact qualification.** Clean wheel install, imports ngoài source checkout, Python/native/version compatibility, resources/schemas, no duplicate implementation files or hidden path hacks.
- **M512.03 — Rebuild reports.** All MD/charts generated from immutable JSON/Parquet/campaign/trace refs; numerics match fullprecision data. Invalid/partial evidence does not produce green badge.
- **M512.04 — Operational reliability.** Cancellation, slow audit sink, memory budgets, cached/stale handle recovery, missing environment, recipe failure and resume trial status. Keep sampler sequence semantics where promised.
- **M512.05 — Docs and Spec update.** Fold this guide into same Mode5 Spec/repo documentation by approved mapping; retain eight-chapter heritage, mathematical errata and evidence levels. Examples on installed package, no nonexistent APIs.
- **M512.06 — Review/handoff.** Deliver patch diffs, source lock, exact commands, small reproduction pack, all phase reports, formula registry and claim matrix. User/maintainer approves integration/publication separately.

### Economics và tests

M5T-111…120. QA can confirm sound pipeline even when no recipe beats baseline. Cannot certify bốn alpha coverage if a route remains blocked; final scope matrix must show partial.

### Deliverables và exit

`mode5_upgrade_handoff.json`, final MD report, source/test/artifact manifests, verified reproduction sample, documentation and performance outcomes. Final status has separate software, research, alpha coverage and independent-validation axes.

**Báo cáo:** exactly what shipped/tested, what was reused, all open limitations, go/no-go per capability.  
**Rollback:** disable opt-in extension/pin previous compatible artifacts; never overwrite old scientific evidence or market data.

---
## 7.8 Rules báo cáo áp dụng cho mọi phase

Các rules này bổ sung agent rules hiện có. Không được bỏ correctness, safety, source provenance hoặc audit vì một report template cũ ngắn hơn. Claude/OpenCode có thể chia writer/reviewer; hai agents dùng cùng context/tests không tự là independent statistical validation.

### 7.8.1 Bắt buộc `report.md` và `report.json`

Mỗi phase có thư mục evidence riêng, append-only theo attempt/revision. Report được rebuild từ stored artifacts, không từ notebook memory. Tối thiểu:

1. Objective, hypothesis và câu hỏi thực sự đã test; những gì chưa test.
2. Source/alpha/data/economic/metric/methodology identities; requested và actual routes.
3. Changed files/symbols, reasoning, impact map và reuse decisions.
4. Sample counts: raw/unique/effective trials, environments, independent-ish episodes, fills/campaigns, actual bars, seeds; không gọi backtests là independent observations.
5. Test results có execution logs/exit codes, synthetic/mocked/source/math/market/native phân biệt.
6. Matrices và numeric results với units, uncertainty, support, masks và null reasons.
7. Failing-before/passing-after evidence cho correctness repairs; intentional selection differences có formula version.
8. Runtime breakdown, cold/warm/cache, copy/allocations/RSS, budgets và canceled/failed work.
9. **Proof capability:** positive/negative controls chứng minh pipeline có thể phát hiện/bác bỏ giả thuyết nào? Có test nào pass vacuously vì không có trades/transitions không?
10. **Potential assessment:** evidence cho opportunity, local flatness, environment coverage, transfer, tail/cost resilience; bottleneck còn lại là data, method, support hay integration?
11. Alternative explanations và falsifiable next action. Không đổi “cần thêm data” thành câu né kết luận âm khi evidence đã đủ.
12. Claim/data-role limitations: reused2024, insufficient coverage, repeated seeds, incomplete pipelines, unsupported route.
13. Exit disposition, reviewer observations, remaining debt owners, exact next-phase prerequisites.
14. Reproduction commands, environment, output hashes và protected-source integrity check.

Không report chỉ “120 tests pass” hoặc “Mode5 better”. Phải biết tests gọi actual code nào, observations nào độc lập và recommendation dựa vào bảng nào.

### 7.8.2 Trạng thái phase và khoa học tách biệt

Technical:

```text
PLANNED | IN_PROGRESS | BLOCKED | TECHNICALLY_VALID | PARTIAL_TECHNICAL_CLOSURE
```

Scientific:

```text
NOT_EVALUABLE | DESCRIPTIVE_ONLY | INCONCLUSIVE
| POSITIVE_WITHIN_SCOPE | NEGATIVE_WITHIN_SCOPE
```

Task dispositions:

```text
IMPLEMENTED_VERIFIED
VERIFIED_EXISTING
NOT_APPLICABLE_WITH_REASON
INSUFFICIENT_EVIDENCE_WITH_PLAN
BLOCKED_CORRECTNESS
DEFERRED_APPROVED
```

`NOT_BENEFICIAL` cho một optimization compute có thể giữ baseline, nhưng không thay requirement diagnostics chưa implement. No evidence ≠ pass. Zero opportunities không pass một test partial-fill/callback policy chưa được exercise.

Không advance phase với blocking technical debt ảnh hưởng consumer tiếp theo. Có thể advance phần độc lập sau explicit partial-scope signoff, không gọi cả phase complete. Không tự merge/publish/deploy từ report.

### 7.8.3 Claim/data integrity

Mọi invalid execution→downstream statistical claim affected là `NOT_EVALUABLE`, dù effect đẹp. Negative results vẫn giữ raw data. Report corrected results là new revision liên kết `supersedes`, không sửa screenshot/table lịch sử.

Giữ classification:

```text
OBSERVED_IN_BUNDLE
REANALYZED_EXISTING_EVIDENCE
SYNTHETIC_CONTROL
ACTUAL_QUANTBT_REFERENCE
ACTUAL_QUANTBT_NATIVE
ACTUAL_MARKET_EXPERIMENT
INDEPENDENT_VALIDATION
```

Một object tồn tại, JSON parse pass hoặc unit test math không đủ đưa status từ first levels lên market/native certification.

## 7.9 Acceptance matrix theo sản phẩm, không chỉ phase

| Product capability | Required gates |
|---|---|
| Diagnostics-first admission | Dossier exists, identity/roles valid, coverage known, technical blockers surfaced |
| Five-axis profiling | Full five axes and six matrices with raw evidence or explicit insufficiency |
| Sensitivity pruning advice | Structural and observed sensitivity separated, multiple metric probes, no auto dead claim |
| Dual environments | Role/timestamp/scaler/overlap/continuous-vs-reset semantics |
| PSR/tail recipes | Units/moments/dependence/tail definition/regret reference correct |
| Local robustness | Independent feasible probes, covariance blind-spot tests, full bad-neighbor retention |
| Pareto compromise | Front/preference/reference invariants, no same-front hypervolume winner claim |
| Auto/advisory router | Dossier-backed decisions, independent whole-procedure evidence for auto scope |
| Public Mode5 execution | Actual route invoked, selected audit consistency, legacy Mode5 and Mode4 unchanged |
| Research reproducibility | Full trial ledger, immutable evidence, report reconstruction, no silent data leakage |

## 7.10 Quan sát cần giữ trong phase cuối

- Diagnostics không chỉ đo một picked winner: một informative candidate set trước calibration phải được evaluate.
- 128/256 profile samples là budget hypothesis, không maturity certificate. Với missing dimensions/rare states, report incompleteness thay claim whole-space robustness.
- Fixed parameter calibration không bảo đảm same PnL mọi environment; qualify theo deployment mandate/horizon.
- Full-data model/selector fit hợp lệ cho today's calibration nhưng historical as-of validation phải fit lại đúng prefix.
- Current Mode4 sampler/meta layer không bị silently kích hoạt; Mode5 extends registry, không đổi target labels hoặc weights Mode4.
- Không gộp tác động của alpha repair vào method improvement. Khi alpha source được sửa, chạy lại baseline/challenger bị ảnh hưởng với cùng phiên bản đã sửa.
- Phát triển formal tuning API không được chặn low-cost profiling/analysis trên cache khi valid; unsupported metric không tự là unsupported alpha.

---

<a id="chapter-8"></a>
# Chương 8 — Direction A freeze, kết luận và Definition of Done

## 8.1 Đóng băng thiết kế triển khai, không đóng băng một kết luận chưa chứng minh

Hướng A giữ nguyên: **diagnostics-first, environment-robust và parameter-robust static calibration**. Bản Upgrade V1 đóng các contracts cần implement và test, không tuyên bố thế giới đã chứng minh HASH/DRO, VWAP/SAM, SC/Pareto luôn thắng hoặc HMA bị loại.

Những observations cũ vẫn có giá trị discovery. Tables/naming không khớp phải sửa bằng errata. Các formula mới PSR/covariance/true-tail cần actual verification, không mượn thành tích T2 để gọi đã thành công.

## 8.2 Khi nào đủ gọi “Mode5 Upgrade V1 complete”?

1. Public upgrade path thật sự yêu cầu valid diagnostic dossier trước formal tuning; legacy route được giữ có nhãn đúng.
2. Mỗi alpha trong scope có five-axis matrices/batteries, actual coverage và recommendation hoặc explicit insufficiency. Không hardcoded family routing.
3. Four selector slots versioned, formulas/units/probes/normalizations/ref benchmarks có oracle tests.
4. Alpha behaviors và QuantBT economics được qualify qua actual route; no handcrafted fills, no loss of amendments/ladder.
5. Existing Mode4/Mode1–3, sampler registry và meta contracts không regression hoặc silently đổi.
6. Old evidence/caches reused theo provenance, missing cells được bổ sung targeted; không chứng minh bằng brute-force compute không có câu hỏi.
7. Search history, all diagnostics/probes, decisions và resource cost được lưu đủ để người khác tái tính.
8. Final report phân biệt technical closure, descriptive diagnostics, transfer evidence và independent economic validation.
9. Documentation examples chạy được trên installed candidate, không source-path hacks.
10. Handoff có exact version/build/source/test commands và rollback; no automatic publish/trade.

Software có thể complete với economic result inconclusive nếu pipeline valid và scope/limitations đầy đủ. Không được tự đánh `COMPLETE_ALL_ALPHAS` nếu một trong bốn primary alpha không qua execution admission; dùng partial closure có approval.

## 8.3 Những kết luận được phép

- “Trên candidate domain/cohort/horizon này, recipe R giữ lower-tail utility tốt hơn baseline với uncertainty X.”
- “Local probes cho thấy center A ít fragile hơn B trong những feasible directions đã kiểm; không claim toàn ball.”
- “HMA min_length có conditional effect trong paths có lower-clamp activity, không structurally inactive.”
- “Chưa đủ evidence để chọn giữa Mode4 và Mode5 cho alpha/scope này.”
- “No candidate đạt mandate hiện tại trong tested set; không chứng minh toàn family không có edge.”
- “Recipe proposed bởi diagnostics đã qua external chronology Y” chỉ khi toàn diagnostics+calibration pipeline có đúng rights/evidence.

## 8.4 Những kết luận không được phép

```text
QMC không overfit / superior universally từ một seed.
HMA/trend không thể fixed-parameter từ hai losing configs.
Positive skew = DRO, negative skew = SAM như luật tất định.
PSR eliminates sample imbalance hoặc xác suất model đúng tuyệt đối.
PCA covariance = Hessian; finite probes guarantee robust everywhere.
Quantile=CVaR; range penalty=LORO; QMC front=NSGA-II search.
Radar score=production eligibility; missing evidence=50/100.
Reviewed2024=untouched confirmation cho recipe chọn bằng2024.
Mode5 calibration return=OOS alpha edge.
```

## 8.5 Ý nghĩa khoa học của lần nâng cấp

Sản phẩm đích không phải một công thức “siêu tối ưu” duy nhất. Đích là một quy trình có thể giải thích:

> Alpha đang được đo trên dataset/economics nào; parameters nào thực sự active; mặt performance có vùng tốt và ổn định hay chỉ peaks; điều kiện nào làm candidates đổi thứ hạng; recipe được ưu tiên dựa trên phép thử nào; uncertainty và counter-evidence là gì; kết quả calibration cuối được kiểm tra đến đâu.

Đó là nền tảng đủ rõ để tư vấn Mode5, mở rộng kinh nghiệm sang alphas mới và tích hợp với QuantBT mà không tạo thêm financial authority.

---

<a id="appendix-a"></a>
# Phụ lục A — Source identity, historical tables và mức kiểm chứng

## A.1 Inputs bất biến

| Ref | File gốc | Bytes | SHA-256 toàn file |
|---|---|---:|---|
| BUNDLE | `export_mode5_direction_a_bundle.zip` | 50,693 | `0707b2d4bf5824b02370c416638a86e7863a20c91216c7c2f0e536ebf2fdaa92` |
| D0 | `MODE5_INVARIANT_AND_ALPHA_PROFILING_SPEC_V1_1.md` | 45,902 | `1800fd3f9929526e84605fb2e114ab179e002dbb8b9213cf9953b2f36d926dc3` |
| D1 | `00_BASELINE_mode5_invariant_master_artifact.json` | 59,174 | `8bae7622fd4174be8e8c16b1ac73a117a7b9d7b8ef6ead32830c32d1bb692b7e` |
| D2 | `01_TEST1_mode5_sampler_tuning_master_artifact.json` | 32,878 | `f14484c1904d8570f492274fa3db0c1df8b9e966d5403bd2d4b138b8213cc360` |
| D3 | `02_TEST2_mode5_direct_formulations_master_artifact.json` | 26,645 | `afaf81e5a07b89361365e476df3ef2ba4465545a408c70a54cc3ccb76aaef65b` |
| D4 | `alphas.zip` | 299,321 | `271e1ebe78db9fb949c058bcdf8a4894974194313c36e098e214e23da0af38c9` |
| D4-SC | `alphas/a_sc.py` | 11,570 | `495d75e35c4ed51c30161a457aad0e9a7a00b5d099666b5d35c0ce1850acb9c2` |
| D4-HMA | `alphas/a_hma.py` | 18,086 | `f6da200feae9b8ce0ae43d3d85bf563e2564c08fda4899440ad96c3fd185a6b5` |
| D4-VWAP | `alphas/a_vwap.py` | 14,427 | `9ab2baaa65088bb0aa980d970833c1fb74f1bc64761c016ae70710196b3d6d74` |
| D4-HASH | `alphas/a_hash.py` | 14,647 | `7bbd1aa478ed53d7339127cd4b93615ded3134e2ad4c2d6cfccfbecbd1b38bf2` |
| D4-GOLDEN | `alphas/golden.py` | 11,565 | `0922c0b72d5af7b04fb28168b05983a8f853050b5a8486b90bd8e9c45c36f3be` |
| D5 | `REGIME_LAB_MODE4_CAUSAL_REBUTTAL_REPAIR_5_PHASES_FINAL_VI.md` | 772,958 | `bf983c2b63dd748d778a3d9c38360bfb6f081cb9b445d7a8044fbae63b2c7434` |

Các paths trong archive chỉ là relative source references, không phải đường dẫn cài package bắt buộc. SHA của toàn archive giữ thêm helpers/raw sources ngoài bốn files chính. Các báo cáo companion của D1–D3 nằm trong BUNDLE, giữ nguyên để reconciliation. Không đính kèm hay chạy `.pyc`/cache được upload.

Nguồn số liệu của Chương3: D1→`metadata`,`score_table`; D2→`metadata`,`matrix_summary`,`winners`,`stress_table`; D3→list16 formulation rows. T2 unique dedup theo alpha+canonical JSON params, không proof of behavioral equivalence. Source lines của D4 là locations trong archive hiện tại.

Mode4 guide [D5] là nguồn phase-report conventions. User xác nhận Mode4 đã implement; guide này không có actual latest Mode4 runtime source, nên M5-01 phải map thực tế và không tạo duplicate infrastructure.

## A.2 Mức kiểm chứng lúc giao file này

```text
Spec/bundle Markdown đã đọc: 5
Master JSON đã parse/tái tạo bảng: 3
Python files alpha đã AST parse: 24
Mathematical assertions mới thực sự chạy: 25
QuantBT full market benchmark mới: NOT_RUN
Actual latest Mode4 source integration: TO_BE_MAPPED_ON_SERVER
Native wheel certification mới: NOT_RUN
Protected originals/core bị sửa: NO
```

25 assertions là arithmetic/statistical identities ở Phụ lục C, không 25 tests chạy alpha/market. 120 tests ở Phụ lục B là acceptance requirements cho agent; không báo như đã pass.

---

<a id="appendix-b"></a>
# Phụ lục B — 120 mandatory acceptance requirements

Test IDs là requirements, không bắt buộc một Git PR/một pytest function cho mỗi dòng. Có thể parameterize và share fixtures, nhưng report phải map mỗi ID sang actual command/assertion/evidence. Các invariant có điều kiện phải giữ điều kiện; không ép implementation sai domain để pass một test quá rộng.

**Legend:** `unit/math`, `source/helper`, `QuantBT synthetic`, `artifact replay`, `real-data targeted`, `integration/system`. Mọi market tests dùng QuantBT authority; custom NumPy mathematics ở đây không phải replacement simulator.

## M5-01 — Baseline, evidence và isolation

| ID | Loại | Tình huống / hành động | Kết quả bắt buộc |
|---|---|---|---|
| `M5T-001` | integration/system | Archive có path traversal, symlink hoặc output trỏ vào source bảo vệ. | Từ chối thao tác không an toàn; không ghi vào inputs/production; tạo manifest trước extraction/copy. |
| `M5T-002` | artifact replay | So SHA-256 của Spec, JSON, alpha trước và sau toàn job. | Original bytes không đổi; output revision mới có parent/source references. |
| `M5T-003` | artifact replay | Bảng prose ghi sampler hoặc fills khác JSON gốc. | Reconciliation report nêu exact record/key; errata không overwrite historical artifact. |
| `M5T-004` | integration/system | Requested sampler khác actual resolved sampler hoặc independent fallback. | Manifest ghi cả hai và lý do; không gọi một mixed run là pure CMA-ES/Sobol. |
| `M5T-005` | artifact replay | Tên “OOS 2024” nhưng interval chỉ 2024-02-01 đến 2024-03-15. | Hiện start/end, scored days và warmup; không diễn giải thành một năm đầy đủ. |
| `M5T-006` | artifact replay | Hai formulations chọn cùng params/cùng execution. | Giữ hai decision records, reuse execution khi identities khớp; không đếm hai samples độc lập. |
| `M5T-007` | integration/system | Package version string giống nhưng code/native hash hoặc module origin khác. | Không reuse certificate/cache ngoài compatibility; actual import provenance xuất trong report. |
| `M5T-008` | artifact replay | Holdout đã dùng chọn recipe hoặc source preset đã tune full-set. | Đổi data role thành exploratory/selection-adjusted; không phục hồi untouched bằng rename file. |
| `M5T-009` | artifact replay | Chỉ có Sharpe/MaxDD/fills summaries nhưng yêu cầu PSR/tail từ raw returns. | Trả MISSING_REQUIRED_INPUT; truy cache/targeted replay, không bịa moments hoặc N. |
| `M5T-010` | source/helper | Mode4 checkout đã có sampler/metric/evidence abstraction tương đương. | Source-binding map reuse exact symbols; không tạo implementation thứ hai để khớp tên proposal. |

Mọi kết quả của nhóm này phải gắn actual command, fixture/data ID và evidence path trong phase report; trạng thái trước implementation là `NOT_RUN`.

## M5-02 — Four-alpha economics và actual execution

| ID | Loại | Tình huống / hành động | Kết quả bắt buộc |
|---|---|---|---|
| `M5T-011` | source/helper | A-SC nhận coeff=1.1 và1.9 khi adapter cast int. | Effective configs trùng được nhận diện; geometry/candidate coverage không đếm hai strategies khác. |
| `M5T-012` | QuantBT synthetic | A-SC opposite signal, thiếu volume và RSI/MFI branches. | Giữ long/flat convention; short signal chỉ đóng long; fallback chỉ báo đúng branch, no accidental short. |
| `M5T-013` | source/helper | A-HMA bốn SL modes, aliases đã hỗ trợ và một unknown value. | Known maps đúng mode; unknown reject; không khôi phục silent default bug đã sửa. |
| `M5T-014` | source/helper | A-HMA thay min_length ở path chạm lower clamp; thử ignored sl_mult/double_up. | Length/indicator behavior đổi đúng điều kiện; ignored keys không được tạo sensitivity/coverage giả. |
| `M5T-015` | QuantBT synthetic | A-VWAP EMA spans ngắn/dài với cùng scored interval. | Có đủ history theo candidate warmup; không giảm scored days riêng cho candidate dài hoặc dùng future warmup. |
| `M5T-016` | QuantBT synthetic | A-VWAP time_stop toggle, inactive time_stop_bars và exit_at_vwap amendment. | Conditional knobs đúng; actual QuantBT nhận amendment sau observation boundary; no unmapped-but-scored. |
| `M5T-017` | QuantBT synthetic | A-HASH TP1=.4 và TP2=.4 trên remaining quantity. | Expected fractions .4/.24/.36 trước lot rounding; actual fills/remaining protective qty reconcile. |
| `M5T-018` | QuantBT synthetic | A-HASH tiny quantity, partial fills, final residual và cooldown. | Lot/min-notional theo capability; không over-close; cooldown chỉ sau flat; dust/status explicit. |
| `M5T-019` | QuantBT synthetic | 2.000 quote notional với one-way fee .0004, round-trip golden fixture. | Phí mỗi fill=.8 trước venue rounding; actual ledger khớp rate contract, không chia đôi phí. |
| `M5T-020` | integration/system | Golden fixed-point helper, unsupported ladder/amendment hoặc coarse route được đưa làm authority. | Chặn claim tương đương; chứng minh public QuantBT actual fills/timing/costs, hoặc gắn scope khác rõ. |

Mọi kết quả của nhóm này phải gắn actual command, fixture/data ID và evidence path trong phase report; trạng thái trước implementation là `NOT_RUN`.

## M5-03 — Metrics, PSR và numerical contracts

| ID | Loại | Tình huống / hành động | Kết quả bắt buộc |
|---|---|---|---|
| `M5T-021` | unit/math | Annualized SR=1,43 daily observations,A=365. | PSR dùng SR_daily đạt khoảng .6326896 trong IID Gaussian toy; annualized-input near1 phải bị test bắt. |
| `M5T-022` | unit/math | Ordinary kurtosis=3 và excess kurtosis=0 cùng Gaussian sample. | Conversion explicit; cùng canonical moments cho cùng PSR; không dùng excess như ordinary. |
| `M5T-023` | unit/math | N<3, zero variance, NaN/Inf hoặc denominator PSR không dương. | Trả typed undefined/invalid status; không score1 hoặc silently replace thành0. |
| `M5T-024` | artifact replay | Daily account series có3 fills nhưng43 observations. | N/moments dùng cùng return series; fills/campaign count là support riêng, không thế chỗ N. |
| `M5T-025` | unit/math | IID và autocorrelated return sequences với cùng marginal moments. | HAC/blocked uncertainty phản ánh dependence theo contract; không hứa SE luôn tăng trong mọi pattern. |
| `M5T-026` | QuantBT synthetic | Loss ở observation đầu episode và first fill fee ngay đầu run. | Initial/pre-block equity được tính; partition money deltas cộng lại bằng whole path, external cashflow tách. |
| `M5T-027` | QuantBT synthetic | Một winning campaign có nhiều partial TP; một losing campaign. | Campaign PF khác fill-based proxy; naming rõ; denominator0/flat campaign có status đúng. |
| `M5T-028` | unit/math | Lower-tail weights [.2,.8], utilities[0,10],alpha=.5. | Tail mean=6 với fractional atom; không thay bằng quantile hoặc average không đúng mass. |
| `M5T-029` | unit/math | Unequal horizons, signed MaxDD legacy, geometric returns và day boundaries. | Canonical MDD positive magnitude, elapsed-time metrics đúng; no sqrt(number_of_window_bars) annualization tùy thời lượng. |
| `M5T-030` | artifact replay | Raw Sharpe và score đã có trade-frequency penalty. | Hai fields/formula IDs riêng; không ghi penalized score vào mean_is_sharpe hay dùng nó làm PSR input. |

Mọi kết quả của nhóm này phải gắn actual command, fixture/data ID và evidence path trong phase report; trạng thái trước implementation là `NOT_RUN`.

## M5-04 — Diagnostic panels, reuse và audit retention

| ID | Loại | Tình huống / hành động | Kết quả bắt buộc |
|---|---|---|---|
| `M5T-031` | integration/system | Đổi fee/funding/slippage hoặc instrument rule trong cùng candidate. | Execution key đổi; chạy lại affected simulation/search; không dùng curve cũ như corrected account. |
| `M5T-032` | integration/system | Alpha code/effective params đổi nhưng raw display name giữ nguyên. | Cache miss hoặc invalidation đúng; code hash và effective digest tham gia key. |
| `M5T-033` | integration/system | Đổi warmup, initial state, terminal-close hoặc carry policy. | Không reuse execution không tương đương; metadata nêu exact state/clock boundary. |
| `M5T-034` | artifact replay | Chỉ đổi objective weights trên metric components đã giữ đủ. | Reuse financial execution; objective/selection revision mới; không tự thay adaptive search history cũ. |
| `M5T-035` | artifact replay | Regret benchmark/reference point thay đổi. | Selection identity đổi; rescore common candidate panel; old objectives không trộn chung scale. |
| `M5T-036` | integration/system | Cache có holdout execution nhưng diagnostic request không có quyền dùng. | Deny dù content hash tồn tại; access/data role không được bỏ qua vì cache hit. |
| `M5T-037` | artifact replay | Nhiều duplicate/pruned/failed Optuna trials dùng ít unique executions. | Trial/evaluation/candidate IDs tách; all trials retained, execution reuse có refs, counts reconcile. |
| `M5T-038` | integration/system | Runtime failure hoặc incomplete panel được trả về objective. | FAIL/invalid không bị encode -1e9 như financial COMPLETE; không cache error thành valid score. |
| `M5T-039` | integration/system | Score retention nhưng diagnostic plan cần campaign tail hoặc return path. | Planner yêu cầu đúng richer inputs hoặc typed incomplete; không tạo diagnostic từ insufficient scalar. |
| `M5T-040` | integration/system | Audit sink chậm, cancellation và memory pressure. | Bounded queue/backpressure; no lost required rows; success sau required flush; partial output được ghi đúng. |

Mọi kết quả của nhóm này phải gắn actual command, fixture/data ID và evidence path trong phase report; trạng thái trước implementation là `NOT_RUN`.

## M5-05 — Environments, data roles và leakage

| ID | Loại | Tình huống / hành động | Kết quả bắt buộc |
|---|---|---|---|
| `M5T-041` | QuantBT synthetic | Sửa future prices sau historical cutoff dùng tạo rolling thresholds. | Past decisions/threshold vintages không đổi; full-development descriptive partition giữ role riêng. |
| `M5T-042` | artifact replay | Cùng historical labels được tạo lại tại current calibration cutoff. | Cho phép descriptive/as-of-current analysis, nhưng không ghi đè labels từng dùng pseudo-live. |
| `M5T-043` | integration/system | Inner validation suffix bị đổi trong scaler/PCA/model selection. | Inner-train fitted transforms không đổi; wrapper phải fit đúng fold, không fit full frame trước split. |
| `M5T-044` | QuantBT synthetic | Hai đoạn cùng regime cách xa nhau được dùng trong analysis. | Không nối prices tạo returns giả; attribution trên continuous path hoặc explicit independent episodes. |
| `M5T-045` | QuantBT synthetic | Reset-flat stress episode và carried full development path. | Results có contract riêng; không cộng best episode returns thành deploy equity. |
| `M5T-046` | artifact replay | Một ngày thuộc cả anchor và endogenous volatility bucket. | Không tăng sample evidence hai lần; view/weights/overlap diagnostics explicit. |
| `M5T-047` | artifact replay | Rare state, no-trade interval, stale hoặc missing enrichment. | Status/support đúng; missing không thành zero-performance/normal regime; không drop riêng unfavorable cells. |
| `M5T-048` | real-data targeted | Candidates có warmup khác nhau và history thiếu đầu kỳ. | Scored interval matched; status không-ready nếu thiếu data; report không chỉ hiển thị nominal dates. |
| `M5T-049` | integration/system | Outcome episode chưa mature tại pseudo-live decision. | Không dùng outcome/recipe/candidate discovered sau cutoff; timestamps và permitted lineage được assert. |
| `M5T-050` | artifact replay | 2024 vừa là stress anchor vừa là holdout chọn recipe. | Một scope chỉ có role được phép; đánh selection-adjusted/retrospective, không independent validation double-use. |

Mọi kết quả của nhóm này phải gắn actual command, fixture/data ID và evidence path trong phase report; trạng thái trước implementation là `NOT_RUN`.

## M5-06 — Geometry, sensitivity và local probes

| ID | Loại | Tình huống / hành động | Kết quả bắt buộc |
|---|---|---|---|
| `M5T-051` | unit/math | Thêm fixed hoặc inactive parameter vào schema. | Khoảng cách active configs và neighborhood coverage không đổi. |
| `M5T-052` | unit/math | Thêm trial rất xa ngoài vùng đã sample nhưng trong declared bounds. | Geometry scale giữ theo schema đã freeze, không theo sampled span. |
| `M5T-053` | unit/math | Log parameter, integer step, categorical branch và boundary. | Feasible transforms/distance đúng units; không arithmetic mean categorical hoặc fractional lots/periods vô nghĩa. |
| `M5T-054` | source/helper | Coupled min/max, atr_fast/slow và TP ordering. | Sample feasible manifold trực tiếp hoặc repair được version; không silent sort làm thay density/meaning. |
| `M5T-055` | artifact replay | Raw probes collide sau casting/rounding/inactive branch. | Count unique effective probes; retain trial rows và collision reason, không thưởng duplicate flatness. |
| `M5T-056` | unit/math | Plain QMC panel bị đưa vào Saltelli estimator; kiểm N=256,D=10. | Reject incompatible design; first/total-order design có3.072 evals khi đúng configuration, count stress multiplier riêng. |
| `M5T-057` | unit/math | Y variance=0 hoặc conditional branch không bao giờ active. | Sensitivity undefined/conditional insufficiency; không gọi mọi parameters dead bằng ST=0 giả. |
| `M5T-058` | real-data targeted | Parameter có ST_Sharpe thấp nhưng tail/cost/holding effect rõ. | Multi-metric activity profile giữ parameter; không auto-delete theo một threshold .02. |
| `M5T-059` | unit/math | f=1-x²-10000y² và top-sample covariance y=0. | Schema transverse probe y=.01 bắt drop1; covariance-only false-flat test phải fail. |
| `M5T-060` | QuantBT synthetic | Bad feasible neighbors, singular covariance, insufficient distinct probes hoặc clipping collisions. | Bad outcomes retained; min-radius/coverage guard; fallback schema probes hoặc INSUFFICIENT, không fake basin certificate. |

Mọi kết quả của nhóm này phải gắn actual command, fixture/data ID và evidence path trong phase report; trạng thái trước implementation là `NOT_RUN`.

## M5-07 — Objectives và selector semantics

| ID | Loại | Tình huống / hành động | Kết quả bắt buộc |
|---|---|---|---|
| `M5T-061` | unit/math | Average regret với common frozen environment benchmark. | Xác nhận algebra tương đương min+lambda*mean-constant; formula không tự được gọi minimax regret. |
| `M5T-062` | integration/system | Best-so-far benchmark cập nhật giữa adaptive trials. | Freeze reference cho stage hoặc rescore toàn comparable panel; objective version mismatch phải bị chặn. |
| `M5T-063` | unit/math | True max regret và min utility chọn khác nhau trên toy panel. | Hai selectors trả đúng theo formulas; benchmark từ tested set không được gọi global optimum. |
| `M5T-064` | unit/math | Scores [.01,.90,.91,.92],alpha=.25 và unequal weights. | Quantile .6775 khác lower-tail mean .01 trong equal toy; empirical weighted tail xử lý fractional mass. |
| `M5T-065` | unit/math | Local fragility gamma=1 có neighbor kém/tốt hơn center. | Objective=min(center,all evaluated neighbors); không giả finite probes là global robust ball. |
| `M5T-066` | unit/math | Cộng100 vào mọi utility của same landscape. | Absolute local downside không đổi; normalized roughness dùng frozen meaningful scale, không center denominator tùy offset. |
| `M5T-067` | unit/math | Composite trộn PSR score với dollar loss/raw Sharpe fragility. | Unit/channel validator reject hoặc explicit frozen normalization; không so những components không cùng meaning. |
| `M5T-068` | unit/math | Pareto objectives đổi signs, zero-range, missing value, dominated outlier. | Directions/reference/normalization fixed; undefined không biến ideal; selection stability và coverage được báo. |
| `M5T-069` | artifact replay | QMC candidate pool với Pareto post-selection nhưng output ghi NSGA-II. | Algorithm provenance phân biệt candidate generation và selector; NSGA-II chỉ khi evolutionary search thực chạy. |
| `M5T-070` | unit/math | Medoid và centroid trên0,1,2,3,100; centroid chưa evaluate/infeasible. | L1/L2 medoid2, nearest mean3; representative theo exact metric; centroid phải evaluate trước selection. |

Mọi kết quả của nhóm này phải gắn actual command, fixture/data ID và evidence path trong phase report; trạng thái trước implementation là `NOT_RUN`.

## M5-08 — Empirical batteries và controlled comparisons

| ID | Loại | Tình huống / hành động | Kết quả bắt buộc |
|---|---|---|---|
| `M5T-071` | artifact replay | Hai selectors dùng cùng full candidate/environment panel. | So selected candidates/components; không gán sampler advantage khi candidate generation chung. |
| `M5T-072` | real-data targeted | TPE/QMC/CMA-ES khác số executions hoặc independent fallback. | Budget/capability/seed matched và actual work bill; mixed sampler label rõ; không winner-only report. |
| `M5T-073` | unit/math | Hai compromise selectors dùng cùng nondominated front. | Same-front hypervolume bằng nhau không được dùng để chọn selector thắng; test compromise quality riêng. |
| `M5T-074` | QuantBT synthetic | Positive world có broad profitable region; null world không edge. | Battery có khả năng nhận diện opportunity và báo false-positive behavior; không hard-code expected winner theo alpha name. |
| `M5T-075` | real-data targeted | Raw outcome tốt hơn nhưng exposure/volatility cao hơn. | Báo raw và train-calibrated risk-matched views; no ex-post OOS risk scaling giả tradable. |
| `M5T-076` | artifact replay | Đổi alpha label breakout/mean-reversion mà matrices giữ nguyên. | Recommendation dựa evidence, không family lookup; naming không đổi diagnostic mathematics. |
| `M5T-077` | real-data targeted | A-HMA QMC/T1 winner so hai distinct T2 configurations. | Targeted transfer/neighbor diagnostics; không loại Mode5 vì T2 thua, không dùng selected winners làm unbiased sample. |
| `M5T-078` | artifact replay | Feature/environment ablation thay scored cohort hoặc prediction target. | Common cohort/target được enforce hoặc label incomparable; reconstruction fit không thành decision-value proof. |
| `M5T-079` | integration/system | Thêm một recipe/radius/window sau khi xem validation. | Hypothesis ledger và data-role revision mới; all attempts retained; không chỉ export winning setup. |
| `M5T-080` | artifact replay | Một seed và43 ngày cho một sampler được đánh superior universally. | Claim validator giới hạn observation; seed/origin uncertainty và support được hiện, không invent replication. |

Mọi kết quả của nhóm này phải gắn actual command, fixture/data ID và evidence path trong phase report; trạng thái trước implementation là `NOT_RUN`.

## M5-09 — Dossier và advisory governance

| ID | Loại | Tình huống / hành động | Kết quả bắt buộc |
|---|---|---|---|
| `M5T-081` | integration/system | Upgrade tuning request không có dossier hoặc dossier unsealed. | Yêu cầu profile/reuse hợp lệ trước calibration; legacy path giữ label riêng. |
| `M5T-082` | integration/system | Dossier đẹp nhưng execution/metric contract invalid. | Technical gate block; human research override không thể biến invalid thành certified. |
| `M5T-083` | unit/math | Same best candidate across environments nhưng global rank Spearman=0. | Rank diagnostic không tự loại alpha; near-optimal intersection giữ candidate đúng. |
| `M5T-084` | artifact replay | N nhỏ, confidence rộng, no trades hoặc tất cả candidates lỗ. | Tách INSUFFICIENT_EVIDENCE/NO_SUPPORTED_CONFIGURATION/technical errors; không mặc định route Mode4. |
| `M5T-085` | artifact replay | Rare negative environment bị bỏ khỏi dossier để đẹp radar. | Environment/status/cardinality reconciliation bắt missing rows; unfavorable valid outcomes giữ nguyên. |
| `M5T-086` | integration/system | Radar có undefined metric hoặc đổi normalization giữa comparisons. | Hiện missing/insufficiency và reference scale; không gán50/100, không so radar incompatible. |
| `M5T-087` | integration/system | Maintainer override recipe advisory với reason. | Override logged, scope/budget/validation plan preserved; không bypass data rights hoặc source errors. |
| `M5T-088` | integration/system | Adaptive recipe router chưa có whole-procedure validation. | Advisory-first; automatic scope experimental/explicit, không gắn production eligibility từ radar cao nhất. |
| `M5T-089` | integration/system | Alpha/economics/search domain/data role thay sau dossier. | Dependency-aware invalidation; phần còn hợp lệ reuse, phần ảnh hưởng phải bổ sung trước tuning. |
| `M5T-090` | integration/system | Tuning chạy rồi mới generate profile quanh winner. | Audit chronology phát hiện; không badge diagnostics-first trừ workflow legacy/post-hoc ghi đúng. |

Mọi kết quả của nhóm này phải gắn actual command, fixture/data ID và evidence path trong phase report; trạng thái trước implementation là `NOT_RUN`.

## M5-10 — Mode5 integration và kế thừa Mode4

| ID | Loại | Tình huống / hành động | Kết quả bắt buộc |
|---|---|---|---|
| `M5T-091` | integration/system | Legacy Mode5 và Modes1–4 với config frozen chạy trước/sau extension. | Không regression contracts/selection/path trong supported scope; new behavior chỉ qua opt-in/version. |
| `M5T-092` | integration/system | User chỉ đổi sampler trong Mode5. | Không tự bật Mode4 meta-selector, đổi objective/data role hoặc learning target. |
| `M5T-093` | integration/system | TPE independent/multivariate/group settings và categorical branches. | Registry actual config đúng; source trials/constraints/gamma/settings được pin và audit. |
| `M5T-094` | integration/system | CMA-ES gặp categorical/dynamic dimensions unsupported. | Reject hoặc explicit independent fallback theo registry; không claim full covariance optimization trên unsupported domain. |
| `M5T-095` | integration/system | Sobol request128/256 với startup/random/fallback và int projection. | Report actual QMC points/sequence/scramble/collisions; không nói toàn panel giữ balance khi đã pha sample types. |
| `M5T-096` | integration/system | Worker-count và sequential/batch optimizer schedule thay. | Fixed-candidate scores stable theo numerical contract; adaptive sequence chỉ exact với schedule có guarantee. |
| `M5T-097` | integration/system | Import Mode4 trials có objective/data horizon khác sang Mode5. | Không reuse scalar scores trực tiếp; rescore allowed artifacts hoặc deny theo objective/frontier compatibility. |
| `M5T-098` | integration/system | Helper tests pass nhưng public Mode5 chưa gọi selected recipe/dossier. | Actual route counters và output lineage assert end-to-end; không chứng nhận bằng mock-only wiring. |
| `M5T-099` | QuantBT synthetic | Protective exit/amend/reject phát sinh tại actual fill khác dự kiến. | Adapter nhận actual feedback; every intent executed/rejected/unsupported; no fabricated fill reconciliation. |
| `M5T-100` | integration/system | Reference/native và score/audit selected replay trên representative four-alpha contracts. | Financial results tương đương trong tolerance; audit retention khác được label; unsupported backend không silent economic fallback. |

Mọi kết quả của nhóm này phải gắn actual command, fixture/data ID và evidence path trong phase report; trạng thái trước implementation là `NOT_RUN`.

## M5-11 — Calibration và economics evidence

| ID | Loại | Tình huống / hành động | Kết quả bắt buộc |
|---|---|---|---|
| `M5T-101` | artifact replay | Mode5 train_index=test_index=full allowed development. | Hợp lệ full-sample calibration nhưng validation_claim=none; không trình bày calibration curve như independent OOS. |
| `M5T-102` | artifact replay | Recipe đã chọn bằng T1/T2 2024 được đánh lại trên cùng2024. | Reuse là retrospective diagnostic; không gọi independent confirmation, không xóa lịch sử access. |
| `M5T-103` | integration/system | Outer calibration origin với diagnostics/sampler/selector learned from full timeline. | Rebuild toàn procedure bằng allowed prefix; candidate generation và meta recipe không đọc future outer returns. |
| `M5T-104` | real-data targeted | Không còn untouched interval sau discovery. | Frozen retrospective evaluation vẫn được báo đúng; independent claim pending, không fabricate holdout hoặc đổi tên dates. |
| `M5T-105` | unit/math | Cost-derived MDE dùng trade notional khác account equity. | Chuẩn hóa allocation và actual turnover; case .001*.064*.1=.064bps/day, không .64bps/day. |
| `M5T-106` | artifact replay | IS score giảm mạnh làm decay nhỏ đi nhưng OOS không tốt hơn. | Không gọi đó là retention/edge improvement; báo absolute OOS quality, risk và both components. |
| `M5T-107` | unit/math | PF retention với GP hoặc GL bằng0; Sharpe ratio retention khi IS gần0/âm. | Undefined statuses, raw GP/GL và absolute differences; không epsilon tạo huge finite wins. |
| `M5T-108` | unit/math | Effect CI straddles0/MDE, wholly harmful, hoặc upper bound dưới MDE. | Distinguish inconclusive/harmful/no economically meaningful effect; validity phải pass trước verdict. |
| `M5T-109` | real-data targeted | Cost/latency stress thay đổi reactive decisions. | Chạy lại QuantBT policy; fixed-fill fee arithmetic chỉ diagnostic, không thay dynamic rerun; same controls preserved. |
| `M5T-110` | artifact replay | Một trong bốn alpha hoặc required contrast blocked, others có good result. | Không phát blanket four-alpha completion/recipe superiority; coverage và scope-specific claims giữ honest. |

Mọi kết quả của nhóm này phải gắn actual command, fixture/data ID và evidence path trong phase report; trạng thái trước implementation là `NOT_RUN`.

## M5-12 — Qualification, docs và reproducibility

| ID | Loại | Tình huống / hành động | Kết quả bắt buộc |
|---|---|---|---|
| `M5T-111` | integration/system | Prepared benchmark nhanh nhưng public output/report tăng cost. | So public và prepared,cold/warm,cache hit/miss,retention giống nhau; không multiplier từ reduced work. |
| `M5T-112` | artifact replay | Tổng trial-env rows lớn nhưng observations overlap/candidate duplicates. | Resource bill tách executed work và independent evidence; không dùng backtest count làm sample N thống kê. |
| `M5T-113` | integration/system | Build Markdown/charts/JSON lại từ sealed evidence trong process mới. | Numeric tables/figure data khớp hashes và values; không lệ thuộc notebook memory. |
| `M5T-114` | integration/system | Report lấy legacy raw score dưới canonical field hoặc không ghi overrides. | Schema/semantic diff bắt mismatch; recipe/dossier/selection digests reconcile. |
| `M5T-115` | integration/system | Chạy docs examples với ordinary candidate wheel ngoài checkout. | Actual imports/resources/core-native pair đúng; no hidden PYTHONPATH/relative-root dependency. |
| `M5T-116` | integration/system | Reload evidence/cache vào session có narrower data rights. | Revalidate access/cutoffs; không inherit old permission chỉ vì artifacts đọc được. |
| `M5T-117` | integration/system | Crash/cancel giữa calibration, selected replay hoặc audit seal. | Partial attempts tồn tại có trạng thái; no double-complete, no silent data loss, deterministic cleanup. |
| `M5T-118` | integration/system | Source originals/core/main branch được theo dõi suốt qualification. | Hashes/working-tree protections giữ đúng scope; không deploy/publish hoặc mutate alpha ngoài approved branch. |
| `M5T-119` | artifact replay | Phase chỉ nộp test count, thiếu hypothesis proof/potential/rerun command. | Report schema gate fail; không advance required dependent phase khi evidence/closure chưa được review. |
| `M5T-120` | integration/system | Final manifest có 12 phase status,120 requirements và scientific claims. | Mỗi gate map actual evidence/waiver hợp lệ; 25 math assertions không bị nâng thành120 pass hay market performance certificate. |

Mọi kết quả của nhóm này phải gắn actual command, fixture/data ID và evidence path trong phase report; trạng thái trước implementation là `NOT_RUN`.


---

<a id="appendix-c"></a>
# Phụ lục C — Mathematical oracle có thể chạy lại

Code sau là reference nhỏ cho formulas và counterexamples của guide. Chỉ dùng Python+NumPy; không import/run QuantBT, không network, không chỉnh source. Nó không implement account/order simulator. Extract nguyên code vào file mới trong workspace lab và chạy `python math_oracles.py` để nhận JSON stdout.

Các production implementations phải được differential-test với reference hoặc độc lập với expected fixtures; copy cùng implementation rồi gọi oracle độc lập là không đủ.

```python
"""Small mathematical oracles, not a backtest engine. Python 3.11+, NumPy.
Run: python math_oracles.py > math_oracle_results.json
No QuantBT API calls, network calls, source writes, or profitability claims.
"""
from __future__ import annotations
import json
import math
import numpy as np


def psr_iid(sr_period: float, n: int, skew: float = 0.0,
            kurtosis_ordinary: float = 3.0, sr_ref_period: float = 0.0) -> float:
    """Classical plug-in PSR; assumptions must be checked outside this oracle."""
    values = (sr_period, skew, kurtosis_ordinary, sr_ref_period)
    if n < 3 or not all(math.isfinite(v) for v in values):
        raise ValueError("invalid sample or moments")
    den2 = 1 - skew * sr_period + (kurtosis_ordinary - 1) * sr_period**2 / 4
    if den2 <= 0:
        raise ValueError("nonpositive PSR variance approximation")
    z = (sr_period - sr_ref_period) * math.sqrt(n - 1) / math.sqrt(den2)
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def lower_tail_mean(x, alpha: float, weights=None) -> float:
    """Exact lower alpha probability mass, with a fractional boundary atom."""
    a = np.asarray(x, dtype=float)
    if a.ndim != 1 or not a.size or not np.isfinite(a).all() or not 0 < alpha <= 1:
        raise ValueError("invalid tail input")
    w = np.ones(a.size) if weights is None else np.asarray(weights, dtype=float)
    if w.shape != a.shape or not np.isfinite(w).all() or np.any(w < 0) or w.sum() <= 0:
        raise ValueError("invalid weights")
    w = w / w.sum()
    remaining, total = alpha, 0.0
    for j in np.argsort(a, kind="stable"):
        used = min(float(w[j]), remaining)
        total += used * float(a[j])
        remaining -= used
        if remaining <= 1e-14:
            break
    return total / alpha


def local_downside(center: float, neighbors) -> float:
    x = np.asarray(neighbors, dtype=float)
    if x.ndim != 1 or not x.size or not np.isfinite(x).all() or not math.isfinite(center):
        raise ValueError("missing or invalid probe panel")
    return max(0.0, float(np.max(center - x)))


def main() -> None:
    rows = []
    def record(name, ok, detail):
        rows.append({"id": name, "status": "PASS" if bool(ok) else "FAIL",
                     "kind": "MATHEMATICAL_ORACLE_NOT_MARKET_BACKTEST", "detail": detail})
    good = psr_iid(1 / math.sqrt(365), 43)
    wrong = psr_iid(1, 43)
    record("O01_PSR_FREQUENCY", 0.632 < good < 0.634 and wrong > 0.999999,
           {"correct_daily": good, "wrong_annual_input": wrong})
    record("O02_PSR_NULL", psr_iid(0, 43) == 0.5, {"value": psr_iid(0, 43)})
    record("O03_PSR_LENGTH", psr_iid(.05, 400) > psr_iid(.05, 40), {})
    record("O04_PSR_KURTOSIS", psr_iid(.1, 100, 0, 9) < psr_iid(.1, 100, 0, 3), {})
    x = [.01, .90, .91, .92]
    record("O05_TAIL_NOT_QUANTILE", abs(lower_tail_mean(x,.25)-.01)<1e-12,
           {"tail_mean": lower_tail_mean(x,.25), "linear_q25": float(np.quantile(x,.25))})
    record("O06_TAIL_FRACTIONAL_ATOM", abs(lower_tail_mean([0,10],.5,[.2,.8])-6)<1e-12, {})
    record("O07_TAIL_ALPHA_ONE", abs(lower_tail_mean(x,1)-np.mean(x))<1e-12, {})
    record("O08_TAIL_SHIFT", abs(lower_tail_mean(np.array(x)+7,.4)-lower_tail_mean(x,.4)-7)<1e-12, {})
    u=np.array([[1.,4.,2.],[3.,2.,1.],[2.,3.,3.]])
    b=u.max(0); lam=.25
    original=u.min(1)-lam*(b-u).mean(1)
    reduced=u.min(1)+lam*u.mean(1)-lam*b.mean()
    record("O09_REGRET_ALGEBRA", np.allclose(original,reduced), {"score":original.tolist()})
    neighbors=[1.,-.2,1.5]; center=2.
    record("O10_GAMMA_ONE", abs(center-local_downside(center,neighbors)-min([center]+neighbors))<1e-12, {})
    record("O11_FRAGILITY_SHIFT", abs(local_downside(center,neighbors)-local_downside(center+100,np.array(neighbors)+100))<1e-12, {})
    coord=np.array([[-.01,0.],[0.,0.],[.01,0.]])
    cov=np.cov(coord,rowvar=False)
    y_step=.01
    record("O12_COVARIANCE_BLIND_DIRECTION", cov[1,1]==0 and 10000*y_step*y_step==1,
           {"covariance":cov.tolist(), "utility_drop_off_sample_axis":1.0})
    a=np.array([2.,1.5,1.,.5,.1]); b=np.array([2.,.1,.5,1.,1.5])
    ranks=lambda z:np.argsort(np.argsort(z)).astype(float)
    rho=float(np.corrcoef(ranks(a),ranks(b))[0,1])
    record("O13_SPEARMAN_NOT_NECESSARY", abs(rho)<1e-12 and np.argmax(a)==np.argmax(b)==0,
           {"rho":rho, "common_best_candidate":0})
    pts=np.array([0.,1.,2.,3.,100.])
    medoid=int(np.argmin(np.abs(pts[:,None]-pts[None,:]).sum(1)))
    near=int(np.argmin((pts-pts.mean())**2))
    record("O14_MEDOID_CENTROID", pts[medoid]==2 and pts[near]==3, {})
    eq=np.array([20000.,20000.,19000.,19000.]); initial=20000.
    deltas=[eq[1]-initial,eq[3]-eq[1]]
    record("O15_EPISODE_PNL_PARTITION", sum(deltas)==eq[-1]-initial,
           {"partition_money_pnl":deltas,"total_money_pnl":-1000.0})
    remaining=1.; close=[]
    for f in (.4,.4,1.):
        q=remaining*f;close.append(q);remaining-=q
    record("O16_HASH_FRACTIONS", np.allclose(close,[.4,.24,.36]), {"fractions_of_entry":close})
    for span,expected in [(30,104),(40,139),(200,691),(700,2418)]:
        n=math.ceil(math.log(1e-3)/math.log(1-2/(span+1)))
        record(f"O17_EMA_{span}",n==expected,{"buckets":n,"epsilon":.001})
    record("O18_EFFECTIVE_INTEGER",int(1.1)==int(1.9)==1,{})
    one_way_fee=.0004;notional=2000.;capital=20000.
    record("O19_FEE_UNITS",abs(one_way_fee*notional-.8)<1e-12, {"fee_quote":.8})
    delta=.001*.064*(notional/capital)
    record("O20_EFFECT_ACCOUNT_SCALE",abs(delta*1e4-.064)<1e-12,{"bps_account_per_day":delta*1e4})
    r=np.array([.01,-.004,.005,-.002])
    sr=lambda z:float(np.mean(z)/np.std(z,ddof=1))
    record("O21_SHARPE_SCALE",abs(sr(2*r)-sr(r))<1e-12,{"risk_free":0})
    record("O22_SALTELLI_BUDGET",256*(10+2)==3072,{"base_N":256,"D":10,"rows":3072})
    result={"schema":"mode5.math_oracles.v1","scope":"math only; no QuantBT/market execution",
            "checks":len(rows),"passed":sum(r['status']=='PASS' for r in rows),"results":rows}
    print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
    if any(r['status']!='PASS' for r in rows):
        raise SystemExit(1)

if __name__ == '__main__':
    main()
```

## C.1 Output thực tế khi biên soạn

```json
{
  "schema": "mode5.math_oracles.v1",
  "scope": "math only; no QuantBT/market execution",
  "checks": 25,
  "passed": 25,
  "results": [
    {
      "id": "O01_PSR_FREQUENCY",
      "status": "PASS",
      "kind": "MATHEMATICAL_ORACLE_NOT_MARKET_BACKTEST",
      "detail": {
        "correct_daily": 0.6326896240940183,
        "wrong_annual_input": 0.9999999393422746
      }
    },
    {
      "id": "O02_PSR_NULL",
      "status": "PASS",
      "kind": "MATHEMATICAL_ORACLE_NOT_MARKET_BACKTEST",
      "detail": {
        "value": 0.5
      }
    },
    {
      "id": "O03_PSR_LENGTH",
      "status": "PASS",
      "kind": "MATHEMATICAL_ORACLE_NOT_MARKET_BACKTEST",
      "detail": {}
    },
    {
      "id": "O04_PSR_KURTOSIS",
      "status": "PASS",
      "kind": "MATHEMATICAL_ORACLE_NOT_MARKET_BACKTEST",
      "detail": {}
    },
    {
      "id": "O05_TAIL_NOT_QUANTILE",
      "status": "PASS",
      "kind": "MATHEMATICAL_ORACLE_NOT_MARKET_BACKTEST",
      "detail": {
        "tail_mean": 0.01,
        "linear_q25": 0.6775
      }
    },
    {
      "id": "O06_TAIL_FRACTIONAL_ATOM",
      "status": "PASS",
      "kind": "MATHEMATICAL_ORACLE_NOT_MARKET_BACKTEST",
      "detail": {}
    },
    {
      "id": "O07_TAIL_ALPHA_ONE",
      "status": "PASS",
      "kind": "MATHEMATICAL_ORACLE_NOT_MARKET_BACKTEST",
      "detail": {}
    },
    {
      "id": "O08_TAIL_SHIFT",
      "status": "PASS",
      "kind": "MATHEMATICAL_ORACLE_NOT_MARKET_BACKTEST",
      "detail": {}
    },
    {
      "id": "O09_REGRET_ALGEBRA",
      "status": "PASS",
      "kind": "MATHEMATICAL_ORACLE_NOT_MARKET_BACKTEST",
      "detail": {
        "score": [
          0.75,
          0.6666666666666667,
          1.8333333333333333
        ]
      }
    },
    {
      "id": "O10_GAMMA_ONE",
      "status": "PASS",
      "kind": "MATHEMATICAL_ORACLE_NOT_MARKET_BACKTEST",
      "detail": {}
    },
    {
      "id": "O11_FRAGILITY_SHIFT",
      "status": "PASS",
      "kind": "MATHEMATICAL_ORACLE_NOT_MARKET_BACKTEST",
      "detail": {}
    },
    {
      "id": "O12_COVARIANCE_BLIND_DIRECTION",
      "status": "PASS",
      "kind": "MATHEMATICAL_ORACLE_NOT_MARKET_BACKTEST",
      "detail": {
        "covariance": [
          [
            0.0001,
            0.0
          ],
          [
            0.0,
            0.0
          ]
        ],
        "utility_drop_off_sample_axis": 1.0
      }
    },
    {
      "id": "O13_SPEARMAN_NOT_NECESSARY",
      "status": "PASS",
      "kind": "MATHEMATICAL_ORACLE_NOT_MARKET_BACKTEST",
      "detail": {
        "rho": 0.0,
        "common_best_candidate": 0
      }
    },
    {
      "id": "O14_MEDOID_CENTROID",
      "status": "PASS",
      "kind": "MATHEMATICAL_ORACLE_NOT_MARKET_BACKTEST",
      "detail": {}
    },
    {
      "id": "O15_EPISODE_PNL_PARTITION",
      "status": "PASS",
      "kind": "MATHEMATICAL_ORACLE_NOT_MARKET_BACKTEST",
      "detail": {
        "partition_money_pnl": [
          0.0,
          -1000.0
        ],
        "total_money_pnl": -1000.0
      }
    },
    {
      "id": "O16_HASH_FRACTIONS",
      "status": "PASS",
      "kind": "MATHEMATICAL_ORACLE_NOT_MARKET_BACKTEST",
      "detail": {
        "fractions_of_entry": [
          0.4,
          0.24,
          0.36
        ]
      }
    },
    {
      "id": "O17_EMA_30",
      "status": "PASS",
      "kind": "MATHEMATICAL_ORACLE_NOT_MARKET_BACKTEST",
      "detail": {
        "buckets": 104,
        "epsilon": 0.001
      }
    },
    {
      "id": "O17_EMA_40",
      "status": "PASS",
      "kind": "MATHEMATICAL_ORACLE_NOT_MARKET_BACKTEST",
      "detail": {
        "buckets": 139,
        "epsilon": 0.001
      }
    },
    {
      "id": "O17_EMA_200",
      "status": "PASS",
      "kind": "MATHEMATICAL_ORACLE_NOT_MARKET_BACKTEST",
      "detail": {
        "buckets": 691,
        "epsilon": 0.001
      }
    },
    {
      "id": "O17_EMA_700",
      "status": "PASS",
      "kind": "MATHEMATICAL_ORACLE_NOT_MARKET_BACKTEST",
      "detail": {
        "buckets": 2418,
        "epsilon": 0.001
      }
    },
    {
      "id": "O18_EFFECTIVE_INTEGER",
      "status": "PASS",
      "kind": "MATHEMATICAL_ORACLE_NOT_MARKET_BACKTEST",
      "detail": {}
    },
    {
      "id": "O19_FEE_UNITS",
      "status": "PASS",
      "kind": "MATHEMATICAL_ORACLE_NOT_MARKET_BACKTEST",
      "detail": {
        "fee_quote": 0.8
      }
    },
    {
      "id": "O20_EFFECT_ACCOUNT_SCALE",
      "status": "PASS",
      "kind": "MATHEMATICAL_ORACLE_NOT_MARKET_BACKTEST",
      "detail": {
        "bps_account_per_day": 0.064
      }
    },
    {
      "id": "O21_SHARPE_SCALE",
      "status": "PASS",
      "kind": "MATHEMATICAL_ORACLE_NOT_MARKET_BACKTEST",
      "detail": {
        "risk_free": 0
      }
    },
    {
      "id": "O22_SALTELLI_BUDGET",
      "status": "PASS",
      "kind": "MATHEMATICAL_ORACLE_NOT_MARKET_BACKTEST",
      "detail": {
        "base_N": 256,
        "D": 10,
        "rows": 3072
      }
    }
  ]
}
```

Những giá trị này chứng minh các identities/điều kiện cụ thể. Không chứng minh PSR, DRO, local probes hoặc Pareto tạo lợi nhuận trên bốn alpha. Market evidence tương ứng phải được tạo ở M5-08/M5-11.

---

<a id="appendix-d"></a>
# Phụ lục D — Report và handoff templates

## D.1 Phase Markdown template

```markdown
# M5-xx — <phase title>

## 1. Objective và scope
Question, hypothesis IDs; what is NOT tested.

## 2. Identity và contracts
Source SHA; alpha hashes; data snapshot; actual import paths; economic,
metric, environment, sampler and formula versions; data roles/cutoffs.

## 3. Changes and reuse
Files/symbols; verified-existing components; behavior-preserving vs
intentional method change; impacted consumers; patch reference.

## 4. Test plan và execution
IDs, actual commands/exit codes, seed, intervals/warmup, parameters,
unique evaluations, bars, fills/campaigns; source/helper/math/market labels.

## 5. Numeric results and matrices
Raw metrics/units/null reasons; confidence/support; artifact refs.

## 6. Economic interpretation
What evidence supports; what it rejects; rival explanations;
comparison held constant; effect of costs/exposure/rare events.

## 7. Proof capability
Positive/null controls, whether pipeline could detect the hypothesis;
untested directions, invalid/missing scopes and vacuous-pass checks.

## 8. Potential and next falsifiable action
What could improve; what evidence would justify more compute;
stop/go rationale, no guaranteed positive result.

## 9. Performance/resource bill
Cold/warm/cache; preparation/strategy/simulation/metrics/report; peak RSS;
planned vs actual; saved work; canceled work and budget compliance.

## 10. Validity, contamination and review
Historical/reviewed/untouched roles; failures and invalidated claims;
writer/reviewer disagreements and resolution; protected paths unchanged.

## 11. Exit and handoff
Technical status; scientific status; blockers/owners; exact next entry gate;
rerun recipe, artifact hashes, rollback and approvals.
```

## D.2 Phase JSON template

Ví dụ cấu trúc PLANNED, không certificate có sẵn:

```json
{
  "schema": "quantbt.mode5_upgrade.phase_report.v1",
  "phase_id": "M5-01",
  "status": "PLANNED",
  "scientific_status": "NOT_EVALUABLE",
  "source_identity": null,
  "input_artifacts": [],
  "alpha_scope": ["A-SC", "A-HMA", "A-VWAP", "A-HASH"],
  "hypotheses_tested": [],
  "requirements": [],
  "reuse_dispositions": [],
  "test_runs": [],
  "numeric_results": [],
  "matrices": [],
  "economic_interpretation": {
    "supported": [], "not_supported": [], "inconclusive": [],
    "alternative_explanations": []
  },
  "proof_capability": {
    "positive_controls": "NOT_RUN", "null_controls": "NOT_RUN",
    "coverage": "NOT_RUN", "vacuous_checks": []
  },
  "potential_assessment": {
    "evidence": [], "bottlenecks": [], "next_falsifiable_actions": []
  },
  "performance": {},
  "data_roles": [],
  "blocking_issues": [],
  "review": {},
  "protected_sources_unchanged": null,
  "reproduction": {},
  "next_phase_ready": false
}
```

## D.3 Hypothesis outcome record

```text
hypothesis_id
question + causal/economic estimand
candidate/env/source/alpha scope
registration time + allowed data role
baseline/control/treatment identities
planned/actual compute and retained observations
point estimate + uncertainty + minimum economic effect + units
validity/support status
result: supported / rejected-within-scope / inconclusive / not-evaluable
mechanism evidence / alternative explanations
references and approved next action
```

Một hypothesis unsupported không tự trigger thêm1000trials. Need quantified unresolved question. Dataset đã dùng để decision scope changes được mark development/reviewed.

## D.4 Final handoff template

```json
{
  "schema": "quantbt.mode5_upgrade.handoff.v1",
  "guide": "QUANTBT-MODE5-UPGRADE-V1",
  "status": "PLANNED",
  "diagnostics_first": "NOT_RUN",
  "alpha_coverage": {
    "planned": ["A-SC", "A-HMA", "A-VWAP", "A-HASH"],
    "valid": [], "blocked": [], "not_run": ["A-SC", "A-HMA", "A-VWAP", "A-HASH"]
  },
  "phases": {},
  "formula_registry": null,
  "public_integration": "NOT_RUN",
  "mode4_and_legacy_regression": "NOT_RUN",
  "evidence_integrity": "NOT_RUN",
  "independent_validation": "NOT_RUN",
  "research_claims": [],
  "limitations": [],
  "candidate_artifacts": [],
  "protected_sources_unchanged": null,
  "publish_or_live_authorized": false
}
```

Final manifest phải điền từ actual artifacts và schemas, không manual set PASS. Package release/version bump theo maintainer riêng; guide không authorize publish dưới cùng1.1.1 với binary khác mà không provenance.

---

<a id="appendix-e"></a>
# Phụ lục E — Mapping vào Spec V1.1 và quyết định sửa

| Spec section | Quyết định trong Upgrade V1 | Phase |
|---|---|---|
| Chương1 Direction A | Giữ diagnostics-first; invariance trong scope/horizon; bỏ tuyệt đối bias/edge claims | M5-01/09/12 |
| Chương2 current code | Chuyển line-history thành map actual Mode4/5 source; reuse registry/engine | M5-01/10 |
| Chương3 T1/T2 | Bảng từ JSON, samplers đúng, source/runtime caveats; keep all old artifacts | M5-01 |
| §4.1 cockpit | Mandatory dossier; technical gate khác advisory; no fake exclusion | M5-04/09 |
| §4.2 mechanics | Three financial streams, costs, holding, exposure, warmup, terminal/gap | M5-02/03/08 |
| §4.3 topology | Effective schema, branch/manifold, coverage, sensitivity design, independent probes | M5-06 |
| §4.4 dual-regime | Roles/overlap/cutoffs/continuous-vs-reset, actual anchors | M5-05 |
| §4.5 invariance | Ranks + near-optimal sets + regret + support; hard-triad legacy only | M5-07/08/09 |
| §4.6 tails | Daily vs campaign vs fills, ES true tail, no skew-to-recipe law | M5-03/08 |
| §4.7 battery | Five retained tests, selectors vs samplers vs pipelines separated | M5-08 |
| §4.8 dossier | Six evidence matrices, uncertain/null states, valid calibration-plan input | M5-09 |
| §5.1 DRO-PSR | Frequency/N/moments; floor+mean identity; true regret option | M5-03/07 |
| §5.2 CMA-SAM | Rename interpretation; local covariance not Hessian; schema transverse coverage | M5-06/07 |
| §5.3 unified | Same-channel units, coefficient/reference version, no double cost | M5-07 |
| §6.1 full_dro_cvar | Quantile legacy vs true lower-tail version; alpha-independent | M5-07/10 |
| §6.2 full_sam_basin | Feasible local probes, evaluated representative, covariance fallback | M5-06/07/10 |
| §6.3 Pareto | Fixed normalization/preferences; front diagnostics ≠ selected-point skill | M5-07/08/10 |
| §6.4 adaptive selector | Evidence-based advisory; auto whole-procedure validation, not radar lookup | M5-09/11 |
| §7 module tree | Research extension thin, actual shared APIs, no new engine | M5-04/10 |
| §7.2 E2E | profile→dossier→seal→calibrate→validate; conditional reuse allowed | M5-09/10/11 |
| Chương8 freeze | Freeze design/contracts; allow positive/negative/inconclusive research | M5-12 |

## E.1 Thứ tự an toàn khi chỉnh file gốc trong repository

1. Tạo branch/workspace có quyền ghi, preserve original Spec và master artifacts bằng hashes.
2. Thêm note `superseded/extended by QUANTBT-MODE5-UPGRADE-V1` hoặc apply chapter-by-chapter changes theo table. Không chỉ append một appendix trong khi body còn nói universal superiority.
3. Sửa named formulas và examples cùng lúc với tests/version IDs; old aliases chỉ replay rõ ràng.
4. Cập nhật actual runner commands sau khi implementation tồn tại và đã test installed environment.
5. Generate benchmark tables/radar từ artifacts, không copy tay numbers.
6. Nộp diff/report từng phase. Không tự thay Mode4 code/rules hoặc chuyển sang Direction B trước khi closure đúng scope.

---

<a id="appendix-f"></a>
# Phụ lục F — Nguồn kỹ thuật và cách sử dụng

Các nguồn dưới đây được kiểm tra khi biên soạn 08/10/2026. Nguồn `stable/latest` mô tả APIs có thể mới hơn lockfiles trên server; **không dùng chúng để tự nâng dependency**. Pin installed versions và đối chiếu actual behavior trong M5-01/M5-10.

- **[S1] Bailey & López de Prado — The Sharpe Ratio Efficient Frontier / Probabilistic Sharpe Ratio.** Original-frequency SR, non-normal moments và uncertainty. https://www.davidhbailey.com/dhbpapers/sharpe-frontier.pdf
- **[S2] Bailey & López de Prado — The Deflated Sharpe Ratio.** Search-selection bias và multiple trials; không thay chronology/independent validation. https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf
- **[S3] SALib sample API và basics.** Structured Sobol/Saltelli design, total evaluation counts và methodological requirements. https://salib.readthedocs.io/en/latest/api/SALib.sample.html ; https://salib.readthedocs.io/en/latest/user_guide/basics.html
- **[S4] Optuna QMCSampler.** Relative search space, first independent trial, power-of-two and scrambling cautions. https://optuna.readthedocs.io/en/stable/reference/samplers/generated/optuna.samplers.QMCSampler.html
- **[S5] Optuna CmaEsSampler.** Supported distributions/fallback và source-trial behavior; actual version required. https://optuna.readthedocs.io/en/stable/reference/samplers/generated/optuna.samplers.CmaEsSampler.html
- **[S6] Optuna TPESampler.** Univariate/multivariate/group settings và adaptive sampling semantics. https://optuna.readthedocs.io/en/stable/reference/samplers/generated/optuna.samplers.TPESampler.html
- **[S7] Foret et al. — Sharpness-Aware Minimization.** Neighborhood-loss objective; applied backtest probes trong guide là một adaptation cần evidence riêng. https://arxiv.org/abs/2010.01412
- **[S8] Rockafellar & Uryasev — Conditional Value-at-Risk for General Loss Distributions.** Quantile versus tail expectation và distributions có atoms. https://sites.math.washington.edu/~rtr/papers/rtr179-CVaR1.pdf
- **[S9] pymoo — Performance Indicators.** Hypervolume/normalization/reference-point interpretation. https://pymoo.org/misc/indicators.html
- **[S10] scikit-learn — LeaveOneGroupOut.** Leave-out nghĩa là không dùng held group khi fit/select; phải thêm chronology constraints trong trading. https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.LeaveOneGroupOut.html
- **[S11] pymoo — NSGA-II.** Evolutionary non-dominated sorting khác post-select fixed QMC panel. https://pymoo.org/algorithms/moo/nsga2.html
- **[S12] scikit-learn — Nested versus non-nested cross-validation.** Selection layer cần outer evaluation; temporal application của guide không dùng random folds của example. https://scikit-learn.org/stable/auto_examples/model_selection/plot_nested_cross_validation_iris.html
- **[S13] scikit-learn — Common pitfalls.** Preprocessing/feature selection đúng train scope. https://scikit-learn.org/stable/common_pitfalls.html
- **[S14] Optuna — Ask-and-Tell.** Trial lifecycle, reporting/pruning và batching semantics. https://optuna.readthedocs.io/en/stable/tutorial/20_recipes/009_ask_and_tell.html

Các nguồn primary giải thích algorithms, không chứng nhận alpha outcomes T1/T2. Economics hypotheses phải được actual QuantBT runs và evidence trong guide kiểm chứng.

**Kết thúc guide. Không có thay đổi production, market rerun mới hoặc deployment permission được thực hiện chỉ bằng việc ban hành tài liệu này.**
