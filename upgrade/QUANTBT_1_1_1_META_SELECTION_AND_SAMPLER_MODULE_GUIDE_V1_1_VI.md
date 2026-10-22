# QUANTBT 1.1.1 — META-SELECTION VÀ WFO SAMPLER INTEGRATION
## Guide V1.1: một module bổ sung, tám phase, Rust-first, không xây lại backtest engine

**Guide version:** `QMS-V1.1`  
**Ngày cập nhật:** 03/10/2026  
**Repository đích:** `BobbyAxerol/quantbt`  
**Baseline yêu cầu:** `quantbt-engine==1.1.1`; companion được công bố: `quantbt-native==0.4.2`.  
**Namespace triển khai:** `QMS-01` → `QMS-08`.  
**Tình trạng:** đặc tả triển khai và nghiệm thu; chưa sửa repository, chạy native backtest hoặc xác nhận module đã tồn tại.

> **Mục tiêu duy nhất:** bổ sung meta-learning từ historical candidate outcomes để chọn params tốt hơn tại các fold WFO, đồng thời nối một số sampler Optuna phù hợp vào đường search hiện có. Meta là opt-in; mặc định, năm mode WFO và các backtest routes giữ nguyên hành vi.
>
> **Primary supported combination:** `mode_4_is_only_robust` + `per_fold_causal`, qua adapter có bằng chứng tương thích. Những tổ hợp meta khác bị từ chối rõ tại endpoint trong V1, thay vì đổi methodology hoặc gắn nhãn causal giả.
>
> **Không nằm trong scope:** xây financial kernel, matcher, orders/fills/accounting/metrics, controller giao dịch mới, broker adapter, hosting platform, database service, regime predictor hoặc market-data collector. Những phần ấy đã thuộc QuantBT/hệ thống hiện có và chỉ được tái sử dụng qua contract.
>
> **Bốn cấu hình search:** legacy TPE, multivariate/group TPE, CMA-ES, Sobol/QMC. Đây là bốn recipes, trong đó hai recipes cùng thuộc TPE. Không triển khai một optimizer mới bằng Rust và không mở sampler tournament vô hạn.
>
> **Rust-first cho phần tính toán mới:** ưu tiên reuse hoặc triển khai pure-numeric kernels trong native crate hiện có. Nếu không phù hợp về capability, chi phí chuyển dữ liệu, vận hành hoặc hiệu năng đã đo, dùng NumPy/Numba với lý do và parity rõ. Không rewrite Optuna, không ép đổi financial backend.
>
> **Chất lượng sản phẩm khác kết quả nghiên cứu:** module phải đúng, có thể tái lập và giữ tương thích. Nó không được hứa mọi alpha đều có edge; một kết quả không tốt không cho phép sửa số, đổi mục tiêu hay mở thêm model để tìm kết quả đẹp.

---

### Phạm vi cập nhật V1.0 → V1.1 đã được duyệt

Bản này hợp nhất trực tiếp vào guide V1, không yêu cầu đọc một tài liệu bổ sung. Chỉ cập nhật:

1. Sửa timestamp: data cutoff khác thời điểm search/decision hoàn tất và khác effective time.
2. Làm rõ việc bảo toàn information budget/phương pháp khi tối ưu tốc độ, chi phí.
3. Làm rõ task identity, compatibility family, training snapshot và late-label revisions.
4. Làm rõ metadata của native Mode 4 so với final meta-selection.
5. Nghiệm thu parity qua cả chuỗi folds, không chỉ một matrix hay một winner.
6. Áp dụng chỉ đạo Rust-first, NumPy/Numba khi không phù hợp, cùng DSA và bố trí dữ liệu tối ưu trong đúng module.

Giữ nguyên tám phase, bốn sampler recipes, target/learner/guard đã khai báo và phạm vi Mode 4 `per_fold_causal`. Không thêm model family, financial subsystem, live controller hoặc một nghiên cứu khác. V1.1 là **phiên bản tài liệu**, không đổi baseline package `quantbt-engine==1.1.1` hoặc tuyên bố các tests đã chạy.

## Điều hướng

[0. Source đã đọc và giới hạn](#s0) · [1. Scope và rules](#s1) · [2. Điểm tích hợp](#s2) · [3. Endpoint và support matrix](#s3) · [4. Samplers và không gian params](#s4) · [5. Toán học meta](#s5) · [6. Archive/causality](#s6) · [7. Flow WFO](#s7) · [8. Adapter/runtime/Rust](#s8) · [9. Host handoff tối thiểu](#s9) · [10. Performance và chi phí](#s10) · [11. Tám phase](#s11) · [12. Evidence và exit gates](#s12) · [13. Config ví dụ](#s13) · [14. Nghiên cứu hiệu quả](#s14) · [15. Definition of Done](#s15) · [16. Nguồn](#s16).

<a id="s0"></a>
## 0. Cơ sở nguồn: phần nào đã xác minh, phần nào cần khóa trên host

### 0.1. Release identity đã xác minh từ publication metadata

PyPI công bố release pair 1.1.1/0.4.2 và attestation cho core [Q1]:

```text
core tag:           refs/tags/v1.1.1
attested commit:    2c811a7faaed3c274e93c60650e16207949f0a59
core sdist SHA256:  4e5f10896ca682f1a313f271a8e1fff30653ccfba23350e8db4b709b70560ae0
core wheel SHA256:  9a1c7af724e543d8cba338206c0b2c64afe1fb3a621f21b2505454c4807b8587
release date:      2026-09-08
```

Các SHA trên là **giá trị publication metadata**, chưa phải tuyên bố đã tải và hash lại release wheel trong phiên soạn guide.

**Giới hạn cần nói thẳng:** không lấy được một checkout đầy đủ tại tag/hash đó qua HTTP trong phiên này. Có trang `main` trả cache phiên bản cũ, trong khi metadata/docs khác trả nội dung mới hơn. Vì vậy không coi các trang `main` là một checkout nhất quán, và không tuyên bố đã chạy full suite của 1.1.1.

Guide dùng ba lớp bằng chứng:

| Lớp | Nguồn đã đọc | Dùng cho điều gì? |
|---|---|---|
| Release metadata | PyPI 1.1.1 và attestation [Q1] | Khóa baseline, không lấy 1.0.7/1.0.8 thay thế |
| Actual source excerpts | Các mục VFY02–VFY05 trong tài liệu source-audit 1.1.1-context [I1] | Xác định seam endpoint → per-fold orchestration → native scorer và giới hạn timing |
| Public docs + lab source | `docs/optimization.md`, công bố runtime, audit/source bundle meta [Q2–Q3, I2–I3] | Tái sử dụng interfaces, chuyển insight thành đặc tả; không copy lỗi lab vào core |

**QMS-01 phải đối chiếu các seams dưới đây với source/wheel thực trên host trước khi sửa.** Đây là gate reconciliation cụ thể, không phải lời cho phép agent tự thiết kế lại nếu chưa đọc code. Nếu source đã khác, ghi exact successor symbol/diff và xin duyệt phạm vi; không giả số dòng cũ là của tag.

### 0.2. Các seams cụ thể đã đọc

[I1] chứa các trích đoạn source sau. Paths `quantbt_candidate/quantbt/...` là đường trong archive lịch sử; agent map sang canonical `src/quantbt/...` trong repository.

| File/symbol | Đoạn nguồn đã quan sát | Ý nghĩa cho module mới |
|---|---|---|
| `endpoint.py::QuantBTEndpoint.walk_forward` | Original lines 1932–1975; nhận `optimization_mode`, `optimization_schedule`, `optimization_config`, trials/seed | Thêm config qua boundary có sẵn; không tạo endpoint backtest khác |
| `walkforward.py::WalkForwardEngine._run_per_fold_schedule` | Original lines 1455–1521 | Fold-local search gọi `self.optimize_params(...)`; Mode 4 causal không evaluate outer OOS để chọn |
| Cùng hàm, original lines 1539–1564 | Gắn selection metadata rồi gán `params_by_fold[fold_id] = selected.params` | **Meta hook nằm sau native selection, trước final params/strategy OOS materialization** |
| `endpoint.py`, original lines 2032–2064 | `native_prepared_wfo`, prepared strategy policies, scorer capability check | Giữ explicit off/auto/require semantics; không mở Rust cho route không support |
| `backends/native_wfo_public.py` | Original lines 39–43, 290–335, 459–481 | Prepared score chỉ cho contracts cụ thể; timing quan sát là `close_target_v2_same_close`, có guards target/fee/runtime |
| `optimization` public objects [Q2] | `SamplerConfig`, `OptunaOptimizer`, `CandidateSelector`, prepared evaluators | Nối factory/config đã có; generic selector không được giả là WFO selector |
| Generic baseline floor [Q2] | Native selection có thể bị trả về warm-start baseline theo objective | Giữ floor ở native stage; không để nó âm thầm ghi đè meta decision sau đó |

Hashes toàn file trong source archive [I1], **không khẳng định bằng hashes của release tag**:

```text
endpoint.py:
45ede55d0d66dd3a30089584b92199a455acca83e8f0418df3305874c28929a6
walkforward.py:
b3da15189cb87d5e6f0080123aeb7f245b4991d61354112049030335c8f3b256
backends/native_wfo_public.py:
e4725ad1f841b42454b2aff967f3e82949b3a9545ad23d7aa85bc4ebf5f232ee
```

### 0.3. Những kết luận không được tự suy từ nguồn

- Generic `CandidateSelector` không mặc nhiên là selector mà mọi WFO mode sử dụng.
- `fold_candidates` không mặc nhiên chứa full eligible trial pool; phải kiểm actual construction.
- Version string `1.1.1` không đủ chứng minh working tree bằng released tag; ghi cả commit/diff/module origin.
- Native capabilities ghi trên README hiện tại có thể là source-tree additions sau release. Chỉ dùng khi handshake/version của host xác nhận.
- Lab có helper `run_event_account` không có nghĩa phải đưa helper đó vào module mới.
- TPE đang cố định tại một WFO callsite không có nghĩa cả repo chưa có sampler factory.
- Scope chặt không cho phép bỏ qua một dependency defect làm kết quả sai. Nếu existing evaluator có bug thuộc lớp khác, mở minimal reproducer riêng và chặn capability bị ảnh hưởng; không mở rộng PR meta thành rewrite accounting.

### 0.4. Phân biệt proposal với API đã tồn tại

Các tên `MetaSelectionConfig`, `MetaHistoryView`, `MetaSelectionDecision`, `optimization_config["meta_selection"]` trong guide là **API/contracts đề xuất cần triển khai**. Chỉ những symbols ở bảng nguồn mới được mô tả là đã quan sát.

Guide không yêu cầu một module độc lập bên ngoài QuantBT hoặc một repo mới. Agent phải tìm tên/config tương đương đã tồn tại để reuse trước khi thêm file.

<a id="s1"></a>
## 1. Scope, non-goals và rules

### 1.1. Phần được thêm

1. Một package cohesive `src/quantbt/optimization/meta_selection/` để quản lý descriptors, historical task views, Ridge và decision records.
2. Adapter mỏng vào existing WFO selection seam.
3. Tái sử dụng/mở rộng existing sampler factory để WFO nhận bốn recipes đã định.
4. Metadata/serialization/tests/docs cần để public endpoint sử dụng và host hiện có tiêu thụ params đã chọn.
5. Tối ưu glue code và sử dụng prepared Rust evaluator hiện có; thiết kế phần tính toán meta mới theo Rust-first qua native crate/capability hiện có. NumPy/Numba là reference hoặc execution fallback được giải thích và kiểm parity, không mặc định production NumPy-first.

### 1.2. Không làm trong PR/module này

Không thêm financial kernel, fee/funding engine, order matcher, portfolio system, metric library, regime ML, new market loader, message bus, database/REST service, broker/live controller, auto-deploy, account kill switch, UI/Portal project hoặc alpha implementations mới.

Không thay mặc định `backend="auto"`, vị trí đóng/mở lệnh, clock của strategy, warmup policy hay fold position policy. Không refactor toàn `walkforward.py` chỉ để làm code mới trông đẹp.

Không triển khai sampler bằng Rust; dùng Optuna/cmaes hiện có. Không mở GP/NSGA-II/CatCMA/LLM/auto-sampler vào roster V1. Các samplers khác đã tồn tại trong generic optimizer vẫn giữ nguyên, không xóa.

### 1.3. Rules bắt buộc

| ID | Quy tắc |
|---|---|
| R01 | Meta tắt theo mặc định; không archive I/O, auxiliary evaluations hoặc thêm RNG draws trên legacy path. |
| R02 | Giữ nguyên năm mode, schedules và routes cũ khi không opt-in. Không tạo Mode 6. |
| R03 | Active/shadow meta V1 chỉ trên Mode 4 + `per_fold_causal` và adapter được qualified. |
| R04 | Unsupported meta combination fail ở preflight trước optimizer/evaluator calls; không silent fallback sang Mode 4. |
| R05 | Sampler-only config không tự bật meta; meta không tự đổi sampler. |
| R06 | Native anchor là exact result của selector cũ tại origin hiện tại; không dùng `max(IS)` thay stock policy. |
| R07 | Một task có đúng một explicit anchor reference; STATIC/control không mang cờ anchor dùng xuyên folds. |
| R08 | Current candidate descriptors chỉ từ current IS; historical labels chỉ từ outcomes đã trưởng thành. |
| R09 | Anchor, candidate, scaler, schema, model và data frontier đều có provenance. Khóa input tại data cutoff; không ép completion/seal timestamp của computation phải trước data cutoff. |
| R10 | Không dùng outer OOS hiện tại để fit, rank, filter hoặc warm-start current search. |
| R11 | Full eligible current pool được chấm; panel chỉ tiết kiệm label acquisition, không giới hạn selection. |
| R12 | Objective của Optuna và native scores giữ đúng; không `tell` predicted meta score thay actual objective. |
| R13 | Missing/failed/censored/undefined metrics là typed status; không biến thành label 0. |
| R14 | Giữ whole-account result của route có sẵn; không ghép reset folds thành live account. |
| R15 | Không tối ưu tốc độ bằng đổi timing, sizing, fees, trade count semantics hoặc strategy callbacks. |
| R16 | Mọi fitting/scaling/normalization/constraints/label-panel policy phải có version và deterministic rule. |
| R17 | Cold start hợp lệ trả native candidate với reason; corrupt history/schema là lỗi, không nuốt bằng broad `except`. |
| R18 | Sampler state thuộc task; không tái sử dụng objective observations từ fold khác như observations của task mới. |
| R19 | Warm-start chỉ dùng params đã biết trước cutoff và chấm lại bằng evaluator hiện tại. |
| R20 | Rust-first cho các kernels tính toán mới; NumPy/Numba khi Rust không phù hợp hoặc thiếu capability, với resolved backend/reason/parity. `require` không đáp ứng thì fail; không đổi financial backend của caller. |
| R21 | Python strategy state không được chia sẻ giữa concurrent candidate accounts. Không nới `n_jobs` ngoài scope đã certified. |
| R22 | Không có public claim speedup hoặc edge nếu chưa đo trên cùng contract/cost/sample. |
| R23 | Thay source economic dependency invalidates affected evidence; đổi prose không ép chạy lại model/engine. |
| R24 | Mọi phase có executed tests, report và exit gate. Technical PASS khác empirical edge PASS. |
| R25 | Sau phase: verify → report → scoped commit → Bobby review. Không tự tạo approval; auto-advance cần chỉ dẫn riêng. |
| R26 | Không direct commit/push/merge vào protected branch; không reset/clean/xóa untracked evidence. |
| R27 | Version 1.1.1 là baseline, không overwrite published wheel/tag. Release version mới do maintainer duyệt. |
| R28 | “Live-compatible” ở module này là select/export/replay qua interface có sẵn; không quyền gửi orders hoặc sửa governance. |
| R29 | Performance-only patch giữ cùng information budget, method và quyết định: không cắt trials/labels/history/features/pool hoặc đổi precision/stopping để đạt tốc độ. Thay đổi các phần này là policy revision, không optimization tương đương. |
| R30 | Parity phải bao gồm chronological decision sequence, task revisions và history mà mỗi fold nhìn thấy. Late labels không mutate snapshots đã seal hoặc làm origin weights đổi không có version. |

Các rules không yêu cầu một kiểm toán toàn bộ repo cho mỗi commit. Chỉ chạy dependencies và invariants mà thay đổi thực sự chạm tới, rồi một regression matrix cuối.

<a id="s2"></a>
## 2. Kiến trúc tối thiểu và điểm nối thực tế

### 2.1. Luồng được thêm — không có financial subsystem mới

```text
Existing public WFO endpoint
    │
    ├─ normalize/validate sampler_config + meta_selection
    │
    ▼
Existing fold-local optimize_params / scorer / native selector
    │                  │
    │                  └─ Optuna sampler được cấu hình
    ▼
Native selection + full eligible IS trial view
    │
    ├─ meta disabled ───────────────────────────────┐
    │                                              │
    └─ meta enabled                                │
          ├─ matured compatible history snapshot  │
          ├─ fit/read frozen Ridge bundle          │
          ├─ score current pool                    │
          └─ immutable meta decision               │
                         │                         │
                         └─────────────────────────┘
                                   ▼
Existing params_by_fold / selection metadata
                                   ▼
Existing strategy output + OOS execution/replay
                                   │
                                   └─ optional label observer:
                                      post-decision evaluation records
                                      → maturity → future folds only
```

Chỉ một `selection_hook` ở đúng boundary và một `outcome_observer` mỏng sau quyết định. Không gọi engine mới trong meta learner. Observer sử dụng existing evaluation adapter; storage provider có thể do caller cung cấp.

### 2.2. Map code thay đổi dự kiến

| Vị trí | Thay đổi tối thiểu | Không được lan sang |
|---|---|---|
| `src/quantbt/endpoint.py` | Parse hai configs, validate matrix, truyền normalized spec và runtime history handle | Matching/sizing/metric factories |
| `src/quantbt/walkforward.py` | Một meta hook trước final fold params; một observer dùng existing scorer | Đổi objective/mode/formula stitching |
| Existing `src/quantbt/optimization/` sampler/config module | Reuse `SamplerConfig`; bổ sung recipe resolution/WFO bridge nếu thiếu | Một factory thứ hai trong meta package |
| `src/quantbt/optimization/meta_selection/` | Typed contracts, descriptors, history views, Ridge, ranking, export | Market I/O, broker state, global background workers |
| Existing research retention/result metadata | Additive references/columns và meta decision | Rename/drop fields của consumers cũ |
| Existing native prepared WFO adapter | Truyền immutable views/reuse buffers phù hợp | Mở cùng timing cho mọi endpoint |
| Existing native crate/capability interface | Pure-numeric meta kernels Rust-first, batched inputs và deterministic output | Không thêm Rust financial engine, sampler implementation hoặc global worker |
| Tests/docs/examples | Module, compatibility, methodology errors, benchmarks | Full market dataset trong wheel |

Tên actual sampler/config file, Rust crate path và W3 facade phải được tìm từ baseline source; không tạo `samplers.py` mới nếu factory đã nằm trong `optimizer.py`/`config.py`.

Một tổ chức package đề xuất, có thể gộp nếu code nhỏ:

```text
optimization/meta_selection/
    __init__.py
    contracts.py       # config, task/decision/model metadata
    descriptors.py    # schema-driven encoding, basis/scaler
    history.py         # as-of view, compatibility, label observer adapter
    ridge.py           # mathematical reference, validation và Rust-first numeric dispatch
    selection.py       # score/guard/winner contract; batched Rust hoặc qualified fallback
    serialization.py   # safe artifact encoding + digests
```

Không nhân bản classes đã có trong optimization hoặc research retention; import/reuse hoặc thêm fields additively.

### 2.3. Seam quan trọng trong `_run_per_fold_schedule`

Trích ý control flow đã đọc trong [I1], không phải patch có thể áp mù theo số dòng:

```text
selected, fold_trials, fold_candidates = self.optimize_params(...)
# evaluate_oos_candidates=False khi mode4/per_fold_causal

native_selected = selected
if meta_is_enabled:
    full_pool = build_view_from_actual_eligible_IS_records(...)
    selected, meta_decision = meta_hook(
        native_selected=native_selected,
        current_IS_pool=full_pool,
        permitted_history=history.as_of(selection_cutoff),
        ...,
    )

# existing metadata merge + params_by_fold + existing OOS path
```

**Không bật `evaluate_oos_candidates=True` trong current Mode 4 call để tiện tạo labels.** Labels được tạo bằng observer sau khi current decision đã freeze, và bị đóng với historical decision cho tới khi available.

Nếu `fold_candidates` chỉ gồm top-fraction replayed candidates, hook phải lấy actual full eligible trial view và enrich raw IS metrics bằng allowed current-IS path. Không suy tên `candidate` nghĩa là domain selection đầy đủ.

Native anchor có thể có native replay metrics chính xác hơn trial proxy. Adapter phải lưu metric/source contract và không so hai loại raw IS Sharpe incompatible trong một feature matrix.

### 2.4. Native stage và meta stage không giẫm nhau

Thứ tự bắt buộc:

```text
native optimizer/scorer → native selector + native baseline-floor
→ record native anchor
→ meta feasibility + predicted-Q guard + min-Y selection
→ final selected params của opted-in run
```

`_apply_baseline_floor` của generic optimizer, nếu đi qua route này, chỉ giữ vai trò native stage. Không chạy lại một raw-IS floor sau meta để ép mọi selection quay lại anchor. Ngược lại, không xóa floor khỏi generic optimizer.

Result phải tách:

```text
raw_best_trial / native diagnostics       # semantics cũ
native_selected_candidate_id              # native policy result
meta_proposed_candidate_id                # proposal của module
selected_candidate_id                     # actual selected policy result
selection_policy / fallback_reason
```

Khi meta disabled, result core fields/exports cũ giữ nguyên; sidecar không xuất hiện nếu không được yêu cầu. Khi meta active, không nhét predicted decay vào cột raw Sharpe/objective của trial.

### 2.5. Metadata phải mô tả đúng final selector

Mode 4 tiếp tục là phương pháp tạo native anchor từ current IS; meta active bổ sung một final policy học từ historical forward outcomes đã trưởng thành. Không gọi final decision là “stock IS-only selection nguyên bản” khi đã dùng lịch sử forward.

Proposed opt-in fields, map vào existing result/claim metadata:

```text
native_optimization_mode = mode_4_is_only_robust
native_selection_policy = existing_mode4_policy_id
native_selection_information_scope = current_IS_only
final_selection_policy = native | relative_sharpe_decay_v1
current_outer_oos_used_for_selection = false
past_matured_forward_used_for_selection = true | false
meta_proposal_uses_past_matured_forward = true | false
meta_history_information_as_of
meta_training_snapshot_id
final_selection_reason / fallback_reason
```

Các flags phản ánh **quyết định thực**, không được điền chỉ từ `meta.enabled`. Meta active và quyết định dùng score đã fit từ history thì flag past-forward là true, kể cả cuối cùng chọn cùng params với anchor. Cold-start quay về native thì final policy là native, flag past-forward cho final decision là false. Shadow giữ final policy native; việc proposal meta dùng history được ghi riêng, không đổi claim của native account.

Current outer OOS không được dùng là điều kiện chronology; nó không biến adaptive history thành untouched validation, không chứng minh arbitrary strategy không lookahead và không xóa research exposure. Giữ tên mode/schedule cũ; sửa/đính kèm actual final-methodology metadata qua existing fields khi opt-in, không tạo Mode 6 hoặc claim engine mới.

<a id="s3"></a>
## 3. Public endpoint contract và support matrix

### 3.1. Bốn recipes, ba trạng thái meta, một primary methodology

Tái sử dụng existing `optimization_config` làm đường khai báo WFO; chỉ expose thêm keyword top-level nếu maintainer muốn và có compatibility tests. Không đổi positional signature.

Proposed fields:

```text
optimization_config.sampler_config
optimization_config.meta_selection
```

`sampler_config` dùng canonical `SamplerConfig` hoặc mapping normalize thành cùng object. Không duy trì hai format khác nhau giữa generic optimizer và WFO.

`meta_selection.mode`:

- `off`: đúng legacy path.
- `shadow`: fit/chấm/lưu candidate khác, actual run vẫn dùng native selection.
- `active`: candidate được meta chọn đi vào existing fold params path.

Shadow có thể phát sinh auxiliary evaluations để học nhưng phải opt-in, charge riêng, không làm đổi native search RNG/objective/candidate pool. Archive policy được chốt trước comparisons để shadow không có hidden training advantage.

### 3.2. Matrix methodology V1

| Mode + schedule | Meta off | Sampler-only mới | Meta shadow/active V1 |
|---|---|---|---|
| Mode 4 + `per_fold_causal` | Giữ nguyên | Có, qua sampler capability tests | **Hỗ trợ chính**, adapter/scorer contract phải đạt |
| Mode 1 + `per_fold_causal` có inner validation | Giữ nguyên nested behavior | Qua actual stage binding | **Chưa hỗ trợ V1**; cần adapter và target cohort riêng trước mở |
| Mode 1 + `per_fold_decay` | Giữ nguyên selection-adjusted behavior | Qua actual stage binding | **Từ chối**: current outer OOS là selection input |
| Bất kỳ mode + `global` hiện được hỗ trợ | Giữ nguyên historical calibration semantics | Theo native study stages/constraints | **Từ chối V1**, không biến global calibration thành fold-causal |
| Mode 2 SBB | Giữ proxy/bootstrap/RNG | Chỉ thay proposal sampler nếu validator/evaluator hỗ trợ | **Từ chối V1**; synthetic/stress outcomes không tự là real forward labels |
| Mode 3 flat-minima | Giữ neighborhood/plateau semantics | Theo native constraints | **Từ chối V1** ngoài combination đã triển khai riêng; không tái định nghĩa mode |
| Mode 5 full-robust | Giữ full-sample calibration | Theo actual study capability | **Từ chối V1**; không gọi full-sample replay là untouched OOS |
| `optimization_mode=none`, fixed backtest/train-test | Giữ nguyên | Không mở vô nghĩa | **Từ chối meta WFO config**, giải thích scope |

Sampler-only support không có nghĩa mọi tổ hợp Optuna/mode đều hợp lệ. Adapter phải kiểm số objectives, constraints, conditional schema, number of optimized dimensions và stage semantics. Unknown/unsupported combinations raise trước first evaluation.

**Không giảm correctness của mode cũ để module mới chạy được.** Khi meta không bật, những combination cũ vẫn hoạt động như trước kể cả không có causal-OOS claim.

### 3.3. Matrix route V1

| Route | Scope tích hợp |
|---|---|
| Public target-series WFO, Mode4/per-fold-causal, existing scorer | Mandatory scalar integration sau QMS-01 |
| Prepared-native public WFO cùng methodology | Dùng cùng hook; mandatory parity khi host/tag hỗ trợ |
| Numba/Python scorer cùng contract | Reference/fallback hiện có, không bị xóa |
| Separate reactive WFO W3 sequential | Conditional adapter trong QMS-06 nếu tag đã có public seam tương đương; **không mở nếu phải viết lại scheduler/account** |
| Fixed-matrix R3B hoặc native WFO V2 specialized | Chưa tự hỗ trợ; distinct proposal schedule/segment semantics phải có own adapter |
| Portfolio/package/arbitrage/options/intrabar standalone routes | Không đổi; generic meta WFO chưa tuyên bố hỗ trợ |

Nếu W3 chưa expose hook phù hợp, file docs ghi `META_ROUTE_NOT_SUPPORTED` và hướng dùng existing compatible route hoặc request adapter sau. Không claim stateful-alpha live equivalence từ scalar target route.

### 3.4. Errors có nội dung, không error chung chung

Dùng existing exception hierarchy nếu có; logical error codes:

```text
META_METHODOLOGY_UNSUPPORTED
META_ROUTE_UNSUPPORTED
SAMPLER_SPACE_UNSUPPORTED
SAMPLER_CONSTRAINT_POLICY_REQUIRED
META_HISTORY_INCOMPATIBLE
META_ANCHOR_INVALID
META_FEATURE_SCHEMA_MISMATCH
META_LABEL_NOT_AVAILABLE
META_METRIC_UNDEFINED
META_NATIVE_CAPABILITY_MISSING
```

Thông báo cần gồm requested mode/schedule/route, phạm vi supported, reason và input field. Không nói “engine lỗi” khi người dùng khai một combination không đúng methodology.

`NO_HISTORY`/`INSUFFICIENT_MATURED_ORIGINS` là fallback hợp lệ, không cùng loại lỗi với tampered archive, duplicate anchor hay wrong schema.

<a id="s4"></a>
## 4. Sampler integration: bốn recipes và mixed parameter geometry

### 4.1. Registry hữu hạn

| Recipe ID đề xuất | Optuna object | Dùng để nghiên cứu | Điều phải giữ rõ |
|---|---|---|---|
| `tpe_legacy` | `TPESampler` với config/RNG đúng baseline | Baseline và backward compatibility | Không tự thay startup, multivariate, constraints hoặc seed của đường cũ |
| `tpe_multivariate_group` | `TPESampler(multivariate=True, group=True)` khi version hỗ trợ | Mixed/categorical/conditional parameters và quan hệ trong các subspaces | Grouping không có nghĩa hiểu mọi constraint kinh tế; report independent fallback dimensions |
| `cmaes` | `CmaEsSampler` với backend `cmaes` được pin | Continuous/mixed-integer numeric geometry, params có tương quan | Không joint categorical bằng cách mã hóa 0/1/2; margin variant là config có qualification, không recipe thứ năm |
| `sobol` | `QMCSampler(qmc_type="sobol", scramble=True)` | Coverage-oriented đối chứng và mixed space có independent categorical rõ | First independent trial, fixed relative space, constraints/rounding/dedup phải được báo |

Random sampler có thể là internal independent fallback của Optuna, nhưng không mở thành một public research recipe mới trong V1. Các lựa chọn generic khác đã tồn tại vẫn hoạt động ở scope cũ.

[S1–S3] mô tả capabilities thư viện. Phải map kwargs theo installed version của 1.1.1: tài liệu `stable` ở thời điểm đọc trả 4.9.0, có một số kwargs deprecated; **không upgrade Optuna để khớp ví dụ trên web**.

### 4.2. Không đưa giả thuyết hình học thành quy luật chọn sampler

Với CMA-ES, dạng tìm kiếm khái niệm:

\[
\theta_i^{(g)}=m_g+\sigma_g C_g^{1/2}z_i,\qquad z_i\sim\mathcal N(0,I).
\]

Covariance giúp biểu diễn các hướng thay đổi phối hợp của biến số. Nó không bảo đảm tìm được flat minimum có OOS tốt và không tự enforce `fast < slow`.

Với TPE, likelihood-ratio sampling sử dụng objective mà WFO đã định nghĩa; objective đó không tự là future-Sharpe prediction. Multivariate/group TPE là một lựa chọn để khai thác interactions, không phép chữa chung cho mọi high-dimensional alpha.

Với Sobol, low-discrepancy trong continuous design space không bảo đảm full feasible pool vẫn cân bằng sau mapping categorical/conditional, rounding và constraints.

**Không triển khai rule `dimensions > N ⇒ chọn CMA-ES`.** V1 trả compatibility report, không một learned auto-sampler. Nghiên cứu trước cho insight về alpha–sampler interaction, không một định luật lựa chọn optimizer phổ quát [I2].

### 4.3. Tái sử dụng search-space contract hiện tại

Giữ syntax public cũ của `param_ranges`/`fixed_params`. Internally normalize sang một view dùng chung:

```text
parameter_name
kind: float | integer | boolean | categorical
scale: linear | log
bounds / step / categories
active_if / conditional branch nếu existing schema hỗ trợ
fixed_value nếu fixed
effective_params_builder identity
constraint policy/version
```

Không viết một DSL constraints mới nếu callback/constraint contract hiện có đã đủ. Nếu tag chưa hỗ trợ conditional schema, document giới hạn và yêu cầu opt-in adapter mỏng; không suy bool-field là điều kiện active.

Mỗi trial giữ `requested_params` và `effective_params` riêng. Candidate ID dùng effective representation + strategy/schema identity. Trial ID vẫn giữ để tái lập sampler behavior; hai trials trùng params không được merge thành một Optuna observation không dấu vết.

### 4.4. Feasibility và joint/independent dimensions

**CMA-ES default V1:** preflight fail khi có dynamic/categorical optimized dimensions không thuộc supported contract. Người dùng có thể opt-in `mixed_space_policy=explicit_independent` nếu existing factory/version hỗ trợ, khi đó metadata ghi rõ numeric dimensions joint và categorical dimensions independent. Không tắt warning để giả toàn space được covariance-optimized.

Mixed-integer margin variant chỉ bật khi dependency pin và parity/space tests đạt. Không tuyên bố bản standard tối ưu được mọi rời rạc.

**TPE group:** ghi group decomposition, schema branches và independent-sampled counts. Boolean/categorical hợp lệ vẫn cần correct descriptor encoding ở meta; sampler hiểu category không sửa được meta encode category sai.

**Sobol:** ghi warmup/first independent trial, sequence position, dimension ordering, scramble seed và transformed unique counts. Budget 128 total attempts không tự tương đương 128 pure Sobol points sau startup/warmstart. Không bỏ điểm hoặc thêm trials âm thầm để có power-of-two đẹp.

Formal constraints sử dụng convention existing optimizer. Nếu sampler không hỗ trợ constrained proposals, bắt `post_filter` rõ. Parameter-invalid có thể reject trước expensive evaluation nếu constraints thuần từ params; strategy-result constraints được chấm từ actual result.

Không inject magic objective `-1e9`, fake COMPLETE hoặc zero metric vào đường mới để vượt constraints. Preserve legacy result behavior khi feature off; normalize record status ở module để không học các failures.

### 4.5. Hình học cho descriptors, tie-break và label panels

- Numeric: transform theo fixed schema/log rules và historical standardizer.
- Categorical: fixed one-hot vocabulary hoặc declared encoding invariant; không assume ordinal.
- Conditional inactive numeric: neutral encoded value **kèm activity flag** theo spec; neutral không đồng nghĩa observed numerical zero.
- Fixed params: giữ trong identity nhưng không tăng dimensions khoảng cách nếu chúng không biến thiên.
- Distance cho panel/tie: numeric normalized distances + categorical mismatch, weight theo logical parameter chứ không số one-hot columns.
- Không gọi parameter-distance là behavioral diversity. Nếu dùng behavior fingerprint, nó phải được tính từ current IS outputs và có definition riêng.

Permuting order của categorical labels cùng schema mapping phải giữ geometry/ranking tương ứng. Unknown category hoặc dimension mismatch phải fail, không pad/reset scaler như code lab.

### 4.6. Warm-start V1: tận dụng kinh nghiệm mà không reuse stale scores

Nội dung được triển khai: caller có thể đưa historical champion/native/meta params đã biết trước cutoff qua existing `initial_trials` hoặc equivalent WFO enqueue seam. Tất cả được chấm lại bằng current evaluator.

- Default warm-start OFF để giữ legacy trajectory.
- Warm-start attempts nằm trong tổng budget đã khai báo; không thêm overhead trials không báo.
- Current IS score, feasibility và descriptors được tính mới.
- Candidate tốt ở fold trước không mang forward score thành objective hiện tại.
- Transfer artifact phải có source availability/schema; không lấy winner từ fold tương lai.
- Giới hạn số seeds từ archive trước outcomes, deterministic tie.

**Chưa làm V1:** warm-start covariance từ old objective records, learned selection giữa samplers, bandit phân bổ budget, meta-score feedback vào proposal density. Những insight này được giữ là extension points, không biến thành scope của module đầu tiên.

### 4.7. Sampler telemetry gọn, có ích

Mỗi study/stage lưu:

```text
resolved sampler class + version + kwargs + seed
requested/actual trials; complete/pruned/failed/duplicates
joint/independent dimensions; conditional branches
unique effective candidates; feasible count; constraint failure reasons
startup vs adaptive counts; CMA completed generations nếu API cung cấp
warm-start count; sequence state/reference
ask/tell order digest; objective scope; actual sampler wall time
```

Không introspect private Optuna internals không ổn định chỉ để tạo dashboard. Nếu một counter không có public capability, ghi `not_exposed` và không suy số bằng phỏng đoán.

<a id="s5"></a>
## 5. Meta-learning: toán học, quyết định và giới hạn

### 5.1. Đơn vị học là một candidate trong một historical decision task

Với origin k, candidate θ và **native anchor hiện tại** aₖ:

\[
I_{k\theta}=SR_{IS,k}(\theta),\quad O_{k\theta}=SR_{FWD,k}(\theta),
\]
\[
D_{k\theta}=I_{k\theta}-O_{k\theta},\qquad
Y_{k\theta}=D_{k\theta}-D_{ka_k}.
\]

Raw IS Sharpe khác penalized objective/temporal score. Module nhận cả `metric_definition_id` và raw value đúng từ existing scorer; không rename objective thành Sharpe.

Y âm nghĩa là gap thấp hơn anchor, **không tự có nghĩa forward cao hơn**. Model không học price direction hoặc LOW_VOL trong V1 này.

### 5.2. Descriptors có version, generic theo alpha schema

Preset tối thiểu đề xuất:

```text
active effective parameter encoding
raw IS Sharpe
log1p(IS activity_count), với activity definition từ existing evaluator
```

Optional descriptors chỉ khi already available từ native IS selection:

```text
temporal support / subperiod dispersion / lower-quantile IS quality
native plateau radius/support/neighbor fragility nếu semantics được qualify
```

Không chạy thêm hàng trăm perturbation backtests chỉ để điền một feature optional. Không hardcode A-SC/A-HMA/A-VWAP trong core. Alpha hoặc adapter cung cấp schema/provider; raw candidates và strategy params giữ nguyên.

Fills, round-trip trades, entries không interchangeable. Freeze activity metric; thiếu thì dùng descriptor profile không chứa field ấy trước fit, không lấy forward fills bù IS fills.

### 5.3. Contrast và standardization

\[
v_{k\theta}=\phi_t(x_{k\theta})-\phi_t(x_{ka_k}).
\]

Transformer φₜ fit từ permitted historical IS records của tasks có labels đã mature, không từ current OOS. Cùng transformer áp cho historical/current candidates trong một fit. V1 không dùng labels để fit scale.

Default numeric transform `origin_balanced_zscore_v1`: tổng weight của candidates mỗi historical origin bằng nhau; parameter range/log encoding lấy từ schema. Categorical vocabulary đã freeze; dùng one-hot với block weights cố định, không tự phóng đại rare category bằng inverse tiny std.

Constant historical numeric feature được đánh dấu; nếu current input ra ngoài support của constant dimension, ghi support violation và fallback theo registered rule, không dùng epsilon scale để tạo extreme score.

Đây là normalization spec mới cần version hóa; **không tuyên bố imported β lab tương đương** khi chuyển từ unweighted scaler/floor 1e-4.

Với canonical anchor ID, \(v_{ka_k}=0\), \(\widehat Y(a_k)=0\). Kiểm bằng identity, không bằng `is_anchor` của bất kỳ control row nào.

### 5.4. Learner V1: Ridge origin-sum, không thêm model family

\[
\widehat\beta_t=\arg\min_\beta\left\{
\sum_{k\in\mathcal A_t}\frac1{M_k}\sum_{\theta\ne a_k}
(Y_{k\theta}-v_{k\theta}^{\top}\beta)^2
+\lambda\|\beta\|_2^2\right\}.
\]

- `learner_id = ridge_origin_sum_v1`.
- Starting `lambda_reg = 10.0`, configurable và freeze trong study; không tối ưu trên final outcomes.
- `min_matured_origins = 12` là conservative integration default, không bằng chứng đủ statistical power; library cho explicit override có metadata nhưng acceptance economic study giữ scope đã đăng ký.
- Anchors không tạo một informative zero row để làm tăng support.
- Mỗi origin được tính một lần, cho dù có nhiều labels hoặc nhiều records cùng candidate.
- `B0_GLOBAL` nghĩa là không dùng market context, **không có nghĩa global schedule hoặc fit từ future**.

Đặt V, y và row weights w:

\[
G=\sum_i w_iv_iv_i^\top+\lambda I,\qquad b=\sum_iw_iv_iy_i,
\quad G\widehat\beta=b.
\]

Dùng `solve`/Cholesky phù hợp hoặc existing certified numeric utility; không tính inverse trực tiếp và không dựng `diag(w)` N×N. Reference có thể dùng whitened rows \(\sqrt{w_i}v_i\). λ>0 giúp normal matrix positive definite về toán học; numerical singular/ill-conditioned cases vẫn phải report, không tự thêm jitter không version.

Complexity tham chiếu: fit O(Nd²+d³), rank O(Pd), memory O(Nd+d²) hoặc streaming sufficient statistics O(d²) **khi basis cố định**. Không cần sklearn dependency chỉ để giải hệ nhỏ nếu NumPy hiện có đủ.

### 5.5. Những insight giữ nhưng cần diễn giải đúng

**Origin balance** ngăn candidate-rich fold lấn át, không làm folds độc lập.

**λ convention:** objective trên tương đương mean-origin loss cộng \((\lambda/K)\|\beta\|²\). Archive lớn lên có thể đổi effective shrinkage. Nếu sau này dùng mean-loss với λ cố định, đó là `ridge_origin_mean_v2`, không đổi âm thầm.

**Coefficient:** β_IS nằm trong standardized coordinates. Raw-unit slope cần scale của chính model vintage. Không viết “β=2.11 ⇒ thêm một raw Sharpe làm decay tăng2.11” nếu chưa đổi đơn vị.

**Target coupling:**
\[
Y=\Delta I-\Delta O,\quad \widehat Q=\Delta I-\widehat Y.
\]

IS feature nằm trong target nên positive coefficient không tự chứng minh dự báo ΔO. Đây không tự là leakage; nó là giới hạn diễn giải phải kiểm bằng OOS outcomes.

**Shrinkage:** method là weighted Ridge; không đưa guarantee James–Stein/Empirical Bayes superiority vào public docs nếu không có assumptions/proof phù hợp decision loss.

**Search vs selection:** sampler thay candidate set; meta thay lựa chọn trong set. Cùng params/data/state/economics không đổi outcome chỉ vì nhãn sampler khác. Evidence alpha–sampler của bundle là hypothesis/scope result, không auto-routing law.

### 5.6. Selection policy V1

\[
\widehat Q_t(\theta)=I_{t\theta}-I_{ta_t}-\widehat Y_t(\theta),
\]
\[
\mathcal E_t=\{\theta\in\mathcal C_t^{valid}: \widehat Q_t(\theta)\ge-\epsilon\},
\qquad \theta_t^*=\arg\min_{\theta\in\mathcal E_t}\widehat Y_t(\theta).
\]

Starting epsilon=0.10 điểm Sharpe cho module mới; là predicted-relative-quality convention, không statistical noninferiority guarantee và không reuse mọi số của lab. Export actual resolved value.

Thứ tự:

1. Kiểm native anchor/current pool/task contract.
2. Fit/load model từ as-of history.
3. Chấm **tất cả eligible current candidates**, không yêu cầu current labels đã tồn tại.
4. Áp existing feasibility/safety exclusions và finite-meta-metric checks.
5. Áp predicted-Q floor; anchor là fallback nếu anchor raw metrics hợp lệ.
6. Chọn min signed Y.
7. Tie rule có total ordering: lấy minimum score, tạo tie set theo tolerance cố định, rồi parameter distance và canonical candidate digest; không dùng non-transitive comparator `abs(a-b)<eps` trong sort.
8. Tạo immutable decision; existing WFO consumes effective params.

Không bỏ guard khi safe set rỗng. Anchor hợp lệ có Q=0 nên safe set rỗng là input/implementation error, trừ explicit native no-candidate status.

Finite failures không được fake anchor. Nếu native winner có Sharpe undefined, trả native behavior qua typed `META_NOT_APPLICABLE_METRIC` nếu policy cho phép; không tạo model label hoặc claim retention.

### 5.7. Một fixture logic để khóa objective

Ví dụ **synthetic**, không phải kết quả thị trường:

| Candidate | IS SR | Yhat | Qhat so anchor | Expected |
|---|---:|---:|---:|---|
| anchor | 1.80 | 0.00 | 0.00 | Eligible fallback |
| x | 2.20 | 0.70 | −0.30 | Reject theo Q floor−0.10 |
| y | 1.50 | −0.60 | 0.30 | Selected |
| z | 0.10 | −1.40 | −0.30 | Reject dù minY thấp |

Test phải đi qua actual module và WFO hook; không chỉ kiểm hàm đã không được runner gọi.

### 5.8. Không ép meta vượt capacity của version đầu

B0 tuyến tính không tự học mọi nonlinear interaction giữa parameters. V1 giữ small deterministic descriptor set; một vài declared interaction descriptors có thể thêm trong profile riêng trước evaluation, không tự tạo toàn bộ pairwise products.

Chưa thêm GP/forest/NN ranker, uncertainty-tuned selector, regime classifier, risk-scaling hoặc drawdown objective. Những targets khác phải có `target_version/selection_policy` khác; không rename relative-decay policy thành tail-risk guard sau khi nhìn drawdown.

<a id="s6"></a>
## 6. Historical candidate interface và no-leakage contract

### 6.1. Module cần một history view, không cần một database service

Default nghiên cứu có thể dùng in-memory bounded records. Persistence dùng existing columnar research retention hoặc caller adapter. Không tạo PostgreSQL/Redis/S3 orchestration trong QuantBT chỉ cho feature này.

Proposed internal records:

| Record | Fields cốt lõi |
|---|---|
| `MetaTaskIdentity` | task_id/revision_id, compatibility_family_id; strategy/schema/metric/economic/route; origin, sampler provenance; explicit current anchor evaluation ID |
| `CandidateISRecord` | requested/effective params; native trial/evaluation ID; current IS metrics, validity/support, descriptors |
| `CandidateForwardRecord` | same candidate, target interval, actual metric provenance, status, label_available_at |
| `MetaTrainingRow` | task/anchor/candidate refs, raw I/O/D/Y/Q, weights/basis reference |
| `MetaModelArtifact` | learner/lambda/normalization versions, input information_as_of, exact training snapshot/task revisions, fit_completed_at, scaler/categories/β, support |
| `MetaSelectionDecision` | native/meta/actual winner; final-policy information metadata; ranking/guards; history/model IDs; data_cutoff, decision_sealed_at, ready_at/effective-time references |

Reuse schemas cùng nghĩa nếu đã tồn tại. Không store toàn bộ equity/fills trong mỗi training row; giữ refs đến authoritative outputs.

### 6.2. Explicit anchor, STATIC và dedup

Một task có duy nhất `anchor_candidate_evaluation_id`; không suy từ first item `is_anchor=True`.

Candidate object không chứa role mutable được copy xuyên folds. STATIC là role của control policy, không có quyền đổi reference của meta task. Khi STATIC trùng current anchor params, có thể dùng chung physical evaluation nhưng hai logical role refs vẫn riêng.

Mỗi label phải thỏa bằng dữ liệu của **cùng origin/window/contract**:

\[
Y_{k\theta}=(I_{k\theta}-O_{k\theta})-(I_{ka}-O_{ka}),
\qquad Q_{k\theta}=\Delta I_{k\theta}-Y_{k\theta}.
\]

Anchor role reorder, candidate list reorder hoặc insertion STATIC không được đổi Y/weights/ranking. Historical IS metrics không được reuse như current IS metrics chỉ vì params giữ nguyên.

### 6.3. Timestamp: data cutoff khác computation/seal/effective time

V1.1 bỏ yêu cầu `historical_anchor_selected_at <= historical_decision_cutoff` khi cutoff mang nghĩa khóa dữ liệu. Search và lựa chọn có thể hoàn tất sau data cutoff mà vẫn hoàn toàn causal.

**Bốn loại mốc, không gộp:**

- `data_cutoff` / `information_as_of`: frontier của input snapshot được phép dùng cho quyết định.
- `*_completed_at`: thời điểm công việc search, fit, validation thực sự hoàn tất.
- `decision_sealed_at`: thời điểm nội dung proposal và references được khóa.
- `effective_at`: thời điểm existing route/host thực sự cho phép params có hiệu lực; không phải chỉ ngày đầu fold.

`selection_as_of` trong guide là tên tương thích cho **information_as_of**, không đồng nghĩa decision đã tính xong lúc ấy. Labels có `label_available_at` riêng.

**Current snapshot ở C = information_as_of:**

```text
market input observations và availability nằm trong source contract tại C
historical label_available_at <= C
historical task_revision_available_at <= C
historical transform/calibration/hyperparameter inputs đều thuộc permitted past
current search + current model fit chỉ đọc snapshot đã khóa tại C
```

Đối với một training task j của quá khứ:

```text
IS descriptors và anchor được tính từ inputs có frontier <= data_cutoff_j
candidate_resolved_at_j <= decision_sealed_at_j
anchor_selected_at_j <= decision_sealed_at_j
panel_sealed_at_j <= first_permitted_forward_economic_action_j
forward outcomes không tham gia candidate/panel/decision trước seal
forward_end_j + declared_reporting_lag <= label_available_at_j
label_available_at_j <= task_revision_available_at_j <= current information_as_of
same-origin metric/schema/economics compatible; labels valid và finite
```

Task revision phải đợi đủ terminal dispositions và publication/reconciliation thực; nếu chúng muộn hơn nominal end+lag thì lấy mốc muộn hơn. Không đặt availability sớm theo một lag mặc định để vượt gate.

Đối với một proposal mới dùng trong lane có readiness/live-equivalence contract:

```text
information_as_of <= search_completed_at
information_as_of <= model_fit_completed_at        # khi fit mới; không áp cho artifact cũ được reuse
max(search_completed_at, required_model_ready_at, validation_completed_at)
    <= decision_sealed_at
ready_at >= decision_sealed_at
effective_at >= max(ready_at, existing_route_not_before)
```

Artifact/model được fit từ trước có thể đã ready trước C. Điều kiện của nó là inputs/training frontier đúng tại C và artifact thực sự available theo clock đang dùng; không bắt fit lại chỉ để có timestamp mới. Cold start không có fit thì field là null kèm status, không bịa completion time.

**Ví dụ hợp lệ:** khóa input 00:00, search xong 00:08, seal 00:09, effective 00:15. Không backdate selected/sealed về 00:00. Labels mới available lúc 00:05 vẫn không được nhập vào snapshot đã khóa ở 00:00, dù fit đang chạy.

Không tự dịch financial target interval để hợp thức hóa computation trễ. Dùng readiness/wait-prefix semantics của existing adapter đã được đăng ký; nếu route không biểu diễn được thì báo limitation, không sửa clocks/account trong module. Seal phải có trước actual effect và trước khi forward outcome được dùng; physical historical data có sẵn trên disk vẫn phải bị đóng với decision logic.

Historical replay lưu riêng `wall_generated_at` và các `simulated_*`/logical availability clocks. Một artifact được tạo hôm nay từ past-only snapshot có thể là retrospective replay, không phải bằng chứng đã phát dự báo thật trong quá khứ. Candidate phát hiện bằng future-inclusive search không được nhập ngược thành past candidate.

Equality chỉ được chấp nhận khi event ordering chứng minh publication trước snapshot. Sampler/selector cũng không được đọc data sinh ra trong thời gian chờ chỉ vì nó đã có trên server. Transformer, imputer, vocabulary, feature selection, λ và panel policy giữ các ràng buộc past-only của study.

### 6.4. Current OOS vẫn đóng dù ở trong storage

Một batch runner có thể materialize future outputs vào disk để tiết kiệm compute. Nhưng `MetaHistoryView.as_of(t)` phải lọc đúng, và scorer/selector-facing objects không expose current/future labels.

Future-suffix mutation test phải đổi:

```text
future market bars
future forward Sharpe/returns
future candidates/anchors
future archive records/model artifact
physical order của batch
```

Earlier native/search/meta decisions không đổi. Việc đổi future labels rồi test một helper không được actual runner dùng là không đủ.

### 6.5. Tách task identity, compatibility family và training-corpus snapshot

**Không dùng một hash cho cả ba vai trò:**

| Identity | Bao gồm | Dùng để làm gì? |
|---|---|---|
| `task_id` | Origin/windows cụ thể, run/study, resolved fold seed, candidate pool, native anchor evaluation ID | Định danh chính xác một quyết định/evaluation task |
| `compatibility_family_id` | Strategy semantics, parameter/descriptor schema, IS/FWD window policy, instrument/timeframe, metrics/economics/scorer contract, native anchor methodology, sampler policy family | Xác định tasks có thể dùng chung learner theo scope đã đăng ký |
| `training_snapshot_id` | Corpus được caller cho phép, information frontier và exact ordered set `(task_id, revision_id, content_digest)` | Tái lập đúng những records/weights được phép dùng ở một lần fit |

**Fold ID, actual cutoff date, resolved fold seed, candidate IDs và current anchor ID không làm family đổi ở mỗi fold.** Chúng vẫn được giữ trong task/provenance. Nominal horizon/window policy thuộc family; actual window timestamps thuộc task. Base sampler recipe/seed-derivation policy được kiểm tương thích; không partition theo từng derived fold seed.

Same family không tự cấp quyền quét mọi files trong storage. Caller chọn corpus hoặc imported snapshots được phép, tránh lẫn kết quả của các research variants/final runs đã bị exposure. Run ID không cần là family key; corpus boundary bảo đảm hai variants không vô tình học outputs của nhau.

Default không pool giữa:

```text
strategy version/semantic family
parameter/descriptor schema và effective parameter semantics
instrument + venue + timeframe
IS/FWD horizons và window policy
raw metric definition / annualization / rf / daily marks
existing evaluator economics và initial-state/fold-boundary contract
native/reference scorer compatibility family
anchor methodology / mode / schedule
sampler policy family
```

Budget/panel/profile changes được version hóa và kiểm theo registered compatibility policy; không coi mọi actual candidate counts khác nhau là một family mới. Mỗi task vẫn phải ghi counts và sampling provenance để không che distribution changes.

Đây là conservative grouping, không yêu cầu copy dataset. Exact physical evaluations được tham chiếu chung khi contracts bằng nhau. Cross-sampler/cross-alpha transfer vẫn ngoài V1.1 nếu chưa có explicit migration/re-anchoring procedure.

Real-market counterfactual, actual live outcome và bootstrap/stress synthetic outcome có `outcome_origin` khác. Learner chỉ đọc cohort được đăng ký, không tự pool để tăng row count.

### 6.6. Label acquisition phải có dữ liệu ngoài winners

Lưu mọi trials/IS diagnostics ở mức compact. Chỉ forward-evaluate một representative panel khi cần tiết kiệm, bằng existing evaluator và owner budget:

- Anchor bắt buộc.
- Một phần top-native-IS.
- Một phần khác về schema/IS behavior.
- Một phần mid/lower eligible controls.
- Union winners của các arms được so sánh, đã freeze trước forward outcome.

Preset acceptance benchmark: cap16 base labels/origin; quotas 1 anchor +5 top +5 diversity +5 control sau dedup, fill remaining bằng deterministic rule. Không áp số16 làm production-only limit không thay được.

Panel không được chọn theo outcome. Không chỉ ghi các winners tốt. `OUTCOME_FAILED`, `NO_VARIANCE`, `INCOMPLETE_WINDOW` giữ records nhưng không được dùng làm finite regression target.

**Panel là information-budget policy, không phải compression lossless.** Chấm full current pool không bù được việc history bị thu hẹp. Performance patch giữ nguyên panel membership/quotas, features và số origins đã đăng ký; giảm 16 labels xuống4, bỏ diversity/controls hoặc đổi sang winner-only là policy revision, không được gọi cùng phương pháp chạy nhanh hơn. Nếu thiếu budget, báo hoặc xin đổi phạm vi trước outcomes; không tự cắt.

### 6.7. Thời điểm chạy observer

Trong mode4 causal:

1. Chọn current native/meta candidates từ past.
2. Seal decision/panel trước khi observer mở current forward view.
3. Existing evaluator thực hiện standardized forward work hoặc trả outputs đã có.
4. Observer chuẩn hóa record và schedule maturity.
5. Lần selection sau chỉ nhìn outcomes đã mature.

Không enqueue synthetic scores vào Optuna study để tạo labels. Auxiliary candidate forward evaluation là **evaluation**, không phải một optimization trial.

Trong deployment host, shadow/counterfactual evaluations là jobs research khi có dữ liệu; module không tự mở worker/cron. Live chỉ trade một candidate không tự sinh outcomes của tất cả alternatives.

### 6.8. Task sealing, late labels và revision semantics

Một task có danh sách evaluations phải hoàn thành được khóa trước forward reveal: panel và required winner/anchor union. Default learner chỉ nhận task khi tất cả thành phần bắt buộc đã có terminal disposition, raw references đã kiểm và revision đã seal.

Các labels FAILED/UNDEFINED vẫn được ghi nhưng bị loại khỏi finite regression targets. Với một sealed revision, M_k là số valid, distinct non-anchor candidates đúng contract; tính lại weights 1/M_k trên tập ấy. Không đủ support thì task có status riêng, không tạo zero labels.

Nếu labels đến sau hoặc source corrections thay tập valid rows:

1. Tạo revision mới của cùng task; không mutate revision cũ.
2. Ghi `task_revision_available_at`, parent revision, lý do, expected/actual membership và hashes.
3. Current fit chỉ chọn revision đã available trong snapshot; mỗi task xuất hiện tối đa một revision.
4. Thay **toàn bộ contribution của origin**, không chỉ append rows mới vào G/b cũ.
5. Earlier model/decision snapshots vẫn tham chiếu revision cũ. Revision mới chỉ ảnh hưởng decisions đủ điều kiện từ thời điểm mới; corrected replay là một attempt/version riêng.

Ví dụ: task cũ có 1 valid label, weight1. Task mới có10 labels thì mỗi weight phải là0,1. Không giữ weight1 cho row cũ rồi append9 rows weight0,1. Tổng weight một origin vẫn bằng1; số matured origins không tăng chỉ vì có task revision.

Sufficient-statistics cache phải có task revision và basis/weight policy trong key. Có thể subtract old contribution rồi add new nếu basis giống và residual/conditioning checks đạt; nếu không, rebuild từ compact raw records. Không duplicate cả hai revisions để lấy thêm support.

Đây là record/provider semantics trong module, không yêu cầu database service, collector hoặc worker mới.

### 6.9. State/serialization và resume

Bộ model an toàn giữ:

```text
β, numeric transforms, category vocab/activity masks, descriptor feature order
loss normalization, λ, target/metric/schema versions
compatibility family, corpus/training snapshot và exact task revisions
input information_as_of + max dependency available_at + fit completion clock
native anchor policy compatibility
support/cold-start policy, decision tie and guard settings
```

Dùng safe numeric payloads, JSON với nonfinite policy và npz `allow_pickle=False` hoặc formats đã được project duyệt. Không tự load pickles từ user/library vào engine.

Resume validate sampler state **và** meta history/basis/task snapshots. Không reconstruct sampler bằng seed rồi giả exact resume nếu ask/tell/RNG state thiếu. Corrupted partial checkpoint fail/explicit fresh-attempt policy, không broad catch rồi quietly recompute và nhập duplicates.

<a id="s7"></a>
## 7. Flow causal chuẩn tại từng fold

### 7.1. Hai vòng học tách biệt

**Sampler:** dùng objective IS của trials trước trong **study hiện tại**.  
**Meta:** dùng historical candidate forward outcomes đã mature qua **các origins trước**.

Không đưa `meta Y` vào current objective để “tăng tốc học”; đó là một thuật toán khác, ngoài V1.

### 7.2. Pseudocode orchestration — chỉ là contract đề xuất

```text
validate_endpoint_combo(mode, schedule, route, sampler, meta)

for fold in existing_chronological_folds:
    cutoff = existing_selection_cutoff(fold)
    history = meta_store.snapshot_as_of(cutoff, allowed_corpus) if meta_enabled else None

    native = existing_optimize_params(
        existing_IS_view(fold),
        sampler=resolved_sampler_for_existing_stage,
        evaluate_current_outer_oos=False,
    )
    # Không đổi cách scorer/selector tạo native winner.

    if meta_enabled:
        task = bind_unique_native_anchor(native, fold, cutoff)
        pool = permitted_full_eligible_IS_view(native)
        model = fit_or_reuse_meta(history, task.compatibility_family_id)
        proposal = select_meta(pool, native.anchor, model)
        decision = seal(
            native, proposal, history,
            information_as_of=cutoff,
            completed_and_sealed_clocks=existing_runtime_clocks,
            final_policy_information=actual_decision_metadata,
        )
        # Không ghi completed/sealed_at = cutoff chỉ để hợp schema.
        chosen = proposal if meta_active else native.selected
    else:
        chosen = native.selected

    publish_existing_params_by_fold(chosen)
    # Existing adapter owns readiness/effective-time semantics; no backdating.
    existing_strategy_and_OOS_path(fold, chosen)

    if configured_label_observer:
        record_post_decision_outcomes_with_maturity(...)
        seal_or_revision_task_after_required_terminal_outcomes(...)
        # Future fits use exact available task revisions, never live mutable rows.
```

Các symbols `existing_*` phải được map thành actual methods ở QMS-01/05; không đưa pseudocode vào docs như callable API hiện có.

### 7.3. Causality của model có học từ previous OOS

Previous OOS đã mature có thể trở thành training history cho quyết định tiếp theo nếu online-update rule được freeze. Không phải leakage tự thân. Báo run là **chronological adaptive/prequential selection**, không nói cả OOS history vĩnh viễn untouched.

Imported historical evidence từng được researcher xem cần `research_exposure` label. Technical chronology sạch không xóa việc đã chọn model theo cùng sample qua nhiều vòng. Final-policy metadata phải theo §2.5; chỉ native stage giữ current-IS-only label, không áp label đó cho meta final decision đã học past forward.

### 7.4. Disabled và shadow parity

Disabled:

```text
native params/trials/objective/seed outputs unchanged
meta/history imports lazy hoặc không xảy ra
new label evaluations = 0
metadata behavior unchanged trừ explicit opted-in diagnostics
```

Shadow:

```text
native params và actual execution unchanged
meta predictions lưu riêng
auxiliary runs có budget/time riêng và RNG streams độc lập
warm-start pool/search trajectory không nhận feedback từ shadow winner
```

Shadow có overhead nên **không** claim wall latency giống disabled. Nếu host dùng real-time deadline, shadow jobs không được làm delayed native activation; chạy tách resource budget hoặc dùng frozen replay để đo.

### 7.5. Fallback hierarchy đúng scope

| Tình huống | Hành động |
|---|---|
| Không đủ matured origins | Native selected params tại cutoff hiện tại, reason rõ |
| Descriptor chưa đủ support/OOD theo frozen rule | Native fallback nếu policy đã registered |
| NaN/corrupt/duplicate anchor/schema mismatch | Typed error hoặc invalid-meta-run; không silent success |
| Native search không có feasible candidate | Giữ existing native failure/no-selection contract; meta không bịa một candidate |
| Meta proposal khác nhưng route chưa hỗ trợ params hot-swap | Vẫn chỉ export/routing qua semantics của route; không thay execution policy |
| External host không chấp nhận artifact | Host xử lý theo existing contract; core không tự quản tài khoản |

Dừng implementation bug không phải scientific no-edge. Valid same winner ở nhiều folds vẫn là outcome có nghĩa, không tự bị coi là copied arm.

<a id="s8"></a>
## 8. Adapter với prepared Rust, Python/Numba và các WFO routes

### 8.1. Rust-first cho phần tính toán, không rewrite các phần đã có

V1.1 chọn Rust-first cho computational blocks mới ngay từ thiết kế: descriptor numeric transforms, origin-weighted accumulation, scoring/guard reduction và các numeric helpers phù hợp. Reuse native crate/ABI/capability của QuantBT trước khi thêm symbol nhỏ; không đợi hoàn thành một implementation Python production rồi mới coi Rust là addon.

Scoring candidates tiếp tục dùng prepared/native paths hiện có theo contract của caller. Rust-first của **meta** không cho quyền đổi financial backend, target clock, precision hoặc behavior của strategy để dễ tăng tốc.

Thứ tự thực hiện:

1. Thiết kế DSA/buffer layout và các ranh giới batch: một input matrix/task, không FFI từng scalar/candidate/bar.
2. Reuse existing Rust kernels hoặc thêm pure-numeric meta kernel nhỏ tại native crate phù hợp, với mathematical reference độc lập.
3. Dùng NumPy cho reference/BLAS/solve hoặc Numba cho loops phù hợp nếu Rust không thuận tiện: capability chưa có, ABI/dependency quá nặng, workload quá nhỏ hoặc overhead end-to-end không có lợi. Ghi lý do cụ thể, không fallback im lặng.
4. Benchmark actual resolved blocks và decision-sequence parity trước khi chọn execution path. Rust có lợi hoặc là primary qualified path thì dùng Rust; nếu fallback được chọn, evidence phải giải thích trade-off.

Không rewrite Optuna/TPE/CMA-ES thành Rust. Python giữ API/orchestration, các samplers dùng implementation đã pin. Không so một native-only kernel với Python end-to-end rồi quảng cáo speedup. NumPy/Numba không được đổi objective hoặc dùng một bản algorithm giản lược để làm fallback.

### 8.2. Giữ các constraints của existing prepared scorer

Source snapshot [I1] cho thấy prepared public WFO có guards cho target types, `target_runtime`, annualization, one-symbol support và percent-equity fee/slippage compatibility. Policy off/auto/require và các guards phải giữ nguyên khi thêm meta.

Một điểm đặc biệt: source native adapter được đọc dùng **`close_target_v2_same_close`** cho direct-target request. Module meta không được tuyên bố nó là next-open hoặc sửa signal để ép parity. Nếu alpha cần event semantics khác, dùng route đang đúng hoặc trả capability limitation.

Khi package/tag không có một advertised prepared feature từ README mới, dùng capability matrix của tag, không port cả runtime feature vào PR meta chỉ để dùng một benchmark mới.

### 8.3. Hai tầng cache khác nhau

**Immutable preparation cache:** calendar indices, train/test slices, temporal shards, prepared OHLC/venue metadata. Có thể reuse khi signatures/lifetime đúng.

**Evaluation cache:** terminal metrics/path của đúng candidate và contract. Existing native exact-analysis reuse không đồng nghĩa được skip mọi adaptive Optuna evaluation. Default giữ policy cache/trial behavior hiện tại.

Meta có cache riêng rất nhỏ:

```text
as-of archive snapshot + task family + basis + λ/policy → model fit
model digest + full IS descriptor matrix digest → predictions
```

Nếu cho phép physical evaluation reuse của repeated deterministic candidate, phải giữ logical trial/tell records và Optuna sequence y hệt contract. Strategy stochastic, mutable callback hoặc unknown purity không được shortcut bằng params hash.

### 8.4. W0/W1/W2 và W3 không gộp lại

Public target-series WFO hook nằm ngoài scorer nên có thể reuse same selection semantics trên certified prepared scalar/static targets.

W3 reactive facade, nếu có trong tag, có candidate/fold-account semantics riêng. Adapter chỉ được thêm khi:

- Có public/native selected-candidate seam trước actual downstream selection.
- Historical/current labels cùng reset/continuous semantics được khai báo.
- Không cần viết financial stitching hay stateful execution mới.
- Existing strategy fill feedback và callback schedule được giữ.
- Meta selection chỉ thêm một boundary theo fold, không callback per bar/per candidate để đọc Python model.

R3B fixed candidate batches và sequential TPE là **sampling schedules khác nhau**. Không đổi sang fixed-batch rồi nói đã tối ưu exact sequential TPE. Opt-in batch schedule cần metadata/benchmark riêng, ngoài default integration.

### 8.5. Pure-numeric Rust path và fallback có kiểm chứng

Thiết kế primary Rust meta path trong QMS-04/QMS-06; QMS-07 profile và tối ưu implementation đó. Reuse existing crate/build/capability mechanism. Không thêm Rust engine thứ hai, không expose financial API mới và không bắt buộc thêm linear-algebra dependency lớn chỉ cho một solve nhỏ.

ABI nội bộ đề xuất nhận theo task/batch:

```text
contiguous float64 descriptor matrix hoặc chunk views
canonical task offsets / row weights / finite label masks
immutable labels của permitted historical snapshot
model coefficients hoặc compact G/b theo basis đã khóa
current IS deltas, validity mask, deterministic candidate/tie keys
```

Outputs: fit/scoring diagnostics, Yhat/Qhat, eligibility và selected index theo **cùng** selection spec. Kernel không đọc market files, unrestricted history, orders/positions hoặc current forward outcomes.

**Bố trí dữ liệu và DSA:**

- Compact typed columnar records cho IDs/status/timestamps; numeric feature block contiguous, tránh Dict/DataFrame allocation cho mỗi candidate. One-hot/conditional mapping được compile một lần theo schema; không dùng ordinal proxy để tiết kiệm chiều.
- Một fit/rank batch hoặc bounded chunks, không PyO3 crossing cho từng bar/candidate. Buffers preallocate/reuse trong run-local lifetime; không share mutable strategy state.
- Accumulate weighted Gram/b thành d×d và d; không tạo diag(w) N×N, không inverse tường minh. Solve bằng routine phù hợp đã kiểm số học; NumPy BLAS/solve được phép là một block fallback khi hợp lý, và phải báo đường đi hỗn hợp thật.
- Winner-only: score O(Pd), tìm minimum score rồi quét tie set theo exact rule trong O(P); không sort toàn pool nếu user không yêu cầu full ranking. Nếu cần full ranked report, giữ đủ scores và sắp đúng total order, không bỏ candidates.
- Kho index history theo family/corpus và revision availability; snapshot quyết định dùng exact task versions. Không dùng latest-revision cache cho một cutoff cũ.
- Float64 theo reference; deterministic reduction/merge order trong lane tái lập. Không bật fast-math, float32, approximate feature compression hoặc parallel reduction đổi policy để lấy tốc độ.

Chỉ release GIL/`detach` theo PyO3 đã pin khi dùng Rust-owned hoặc read-only buffers với lifetime/ownership hợp lệ; không truy/mutate Python objects khi thả GIL [S6]. Không hứa zero-copy nếu safety buộc copy: đo bytes và charge conversion cost.

**Runtime policy đề xuất cho meta khi bật:**

```text
implementation = rust_first
native_batch_policy = auto | require
fallback_implementations = [numpy, numba]   # thứ tự/capability được resolve trước run
```

`auto` ưu tiên qualified Rust path. Nếu không phù hợp, resolve NumPy/Numba và lưu `requested_backend`, `selected_backend_by_block`, `fallback_reason`, native/dependency version, JIT warmup nếu có, và benchmark disposition. `require` thiếu capability hoặc không đạt parity thì fail, không tự fallback. Cấu hình này không thay `native_prepared_wfo` hay global financial `backend`.

NumPy là reference hoặc qualified runtime fallback. Numba dùng numeric loops phù hợp, nopython path được kiểm và không fast-math mặc định; charge cold compilation riêng với warm compute, không tính warm-only như total first-run latency. Không cần mọi block có cả ba implementations; chỉ giữ paths thật sự được dùng và kiểm được.

Rust-first không đồng nghĩa chấp nhận native path chậm hơn, sai winner hoặc phá compatibility. Fallback là một engineering disposition có bằng chứng, không giấy phép bỏ nghiên cứu Rust hoặc bỏ chức năng. Tắt meta vẫn zero new archive/evaluation work và giữ legacy dependencies/behavior.

### 8.6. Numerical parity và threshold stability

Rust/NumPy có thể khác summation/FMA/BLAS order. Tests phải bao gồm:

- Fit residual/solution tolerance, score tolerance và selected params exact khi không gần boundary.
- Các candidates sát Q floor/tie tolerance.
- Reference recomputation cho near-boundary set nếu fast kernel không đảm bảo same policy winner; record fallback.
- Permutation và chunk-size invariance trong tolerance đã chốt.
- Không nâng tolerance theo kết quả cần PASS.

Không dựa vào một max coefficient error nhỏ để kết luận winner giống nhau. **Decision parity** là một điều kiện riêng. Fallback của fast path phải đủ rộng để bao phủ mọi candidate có thể đổi eligibility/winner; nếu không có error bound đủ tin cậy thì recompute toàn fit/rank stage bằng reference, không đoán một top-K nhỏ để kiểm.

### 8.6.1. Parity xuyên toàn bộ chronological folds

Benchmark fixed matrix là cần nhưng chưa đủ. QMS-07/QMS-08 phải chạy một sequential replay trên cùng inputs, study/sampler protocol, task revisions và initial model/history snapshot:

```text
fold k inputs/history → features/weights → scores/eligible/tie set
→ selected effective params/fallback → label-panel/winner refs
→ next available task revisions → model/history input của fold k+1
```

Reference và optimized path phải khớp logical task/candidate identities, selected params và validity decisions; numeric arrays được so với tolerance đã đăng ký. So đủ `native_selected`, meta proposed, actual selected, guard/tie reasons, panel membership, training snapshot/revisions, warm-start seeds (nếu được bật) và resolved RNG/ask-tell trace của lane tương đương.

Model/build artifact hashes có thể khác vì backend hoặc bytes coefficients khác trong numerical tolerance; từng hash vẫn phải đúng payload của nó. Không ép binary artifact hashes bằng nhau, nhưng task membership/revision references, input information và policy decisions phải tương đương đúng contract.

Nếu một sai khác nhỏ làm winner khác, đó là parity failure hoặc cần reference fallback; không lấy Sharpe cuối gần nhau để PASS. Trong test tích hợp có thể reuse sealed full-label fixtures/outputs, không phải chạy lại market matrix cho mọi subcase.

Để đo riêng selector, warm-start OFF hoặc cùng canonical seed list độc lập với arm. Native arm lấy native winner cũ còn meta arm lấy meta winner cũ sẽ thay candidate pools; đó là search–selection feedback policy riêng, không còn same-pool comparison. Giữ nguyên scope, không mở feedback policy đó trong bản cập nhật này.

Auxiliary observer không dùng chung mutable callback state/RNG với main run. Cần fixture gần Q floor và tie threshold tại fold đầu, rồi theo dõi ảnh hưởng tới các folds sau; cũng cần resume và late-label revision ở giữa chuỗi. Invariance trước future data vẫn là điều kiện riêng, không thay bằng performance parity.

### 8.7. Versioning native

Baseline 1.1.1/0.4.2 dùng làm legacy oracle/replay reference. Nếu reuse được native exports hiện có, giữ companion dependency khi compatible; NumPy/Numba fallback phải báo đúng capability. Không tự nói published native0.4.2 đã có kernels mới của guide.

Nếu thêm Rust symbols/ABI, cần new native build/version và phối hợp core compatibility policy. Không ghi đè wheel 0.4.2 hoặc tự claim old wheel có capability mới. `native=require` thiếu symbol phải fail; `auto` mới có documented meta-only fallback, không đổi financial backend.

<a id="s9"></a>
## 9. Interface cho host/live: chỉ handoff params, không xây controller

### 9.1. Module trả một decision, host hiện có tiêu thụ

Cùng pure selection function có thể dùng ở WFO historical loop và research worker tại thời điểm hiện tại. Nó trả:

```text
selected effective params
native anchor ID và native selection reason
meta model / history / candidate pool digests
selection_as_of = information_as_of, data watermark và task revision snapshot
decision_sealed_at / ready_at / existing effective-time refs (không backdate)
final-policy information scope theo §2.5
selection reason / fallback / support
source strategy/schema/metric compatibility
ready_at từ existing job runtime nếu được cung cấp
```

Module không tự tạo service, schedule jobs, broker orders hoặc quản pending position. Reference notebook/host example chỉ minh họa gọi selector và export decision qua boundary hiện có.

### 9.2. Cutoff, availability, completion, seal và effective time

| Mốc | Owner / nghĩa |
|---|---|
| Market/IS `data_cutoff` = `information_as_of` | Existing WFO/host khóa input snapshot; không phải thời điểm tính xong |
| `label_available_at` / `task_revision_available_at` | History interface quyết định phiên bản tri thức nào có thể đọc tại cutoff |
| `search_completed_at` / `model_fit_completed_at` / `validation_completed_at` | Existing runtime ghi completion; cached old model có ready timestamp riêng |
| `decision_sealed_at` / `ready_at` | Khóa proposal và thời điểm artifacts đầy đủ; không điền bằng cutoff để dễ hiển thị |
| `effective_at` / activation | Existing route/host áp params; không do Ridge quyết định |

Áp predicates tại §6.3. Search xong sau data cutoff là bình thường nếu chỉ dùng snapshot đã khóa. Trước ready/seal không được có effect của params mới. Labels available trong lúc tính không tự lọt vào snapshot cũ.

Trong backtest, dùng readiness contract hiện có hoặc declared selection lag của adapter; không dịch target window ngầm. Nếu route không biểu diễn được clocks phù hợp cho live-equivalence claim, ghi limitation; không viết lại controller. Lưu riêng wall và replay clocks, không biến một historical replay hôm nay thành một decision đã tồn tại trước đây.

### 9.3. State/fold/policy request không tự đổi strategy state

V1 trigger là existing fold schedule. B0 không dùng external regime state và không trigger refit tùy market.

Nếu host về sau gọi cùng selector sau một state event, đó là **policy ngoài module** phải có own as-of snapshot, event dedup và cadence contract. Không gọi nó là hành vi đã được benchmark ở V1.

Nếu same params được chọn, host có thể revalidate version theo logic hiện có; module không reset indicators/account. Nếu có open position, existing adapter quyết định carry/wait-flat/amend. Module không đổi stop/TP của position cũ hoặc ép flat để quyết định trông tốt hơn.

### 9.4. Những gì cần để load model không có future

Artifact cần có full descriptor schema/scaler/β/archive frontier. Weights-only không đủ. Host không được dùng snapshot mới hơn simulation cutoff trong historical replay.

Một model hiện tại học toàn bộ lịch sử đã mature có thể dùng cho decisions tương lai. Nó không được dùng để replay quá khứ rồi gọi causal. Live readiness không phải performance certification hoặc quyền deploy.

Reference consumer chỉ verify artifact, gọi pure selection hoặc đọc decision và truyền params tới interface đã tồn tại. Credentials, broker connectivity, R1/R2 gates và automatic approval nằm ngoài PR này.

<a id="s10"></a>
## 10. Performance, tài nguyên và giá trị của từng tối ưu

### 10.0. Performance-only phải bảo toàn thông tin và phương pháp

**Hợp đồng bắt buộc:** cùng input information, cùng policy, cùng logical work đã đăng ký và cùng decision sequence. Chỉ giảm công việc dư, allocations/copies/I/O không cần thiết hoặc thực thi cùng phép tính hiệu quả hơn.

| Thay đổi | Phân loại và điều kiện |
|---|---|
| Weighted accumulation không NxN W; prepare/index/cache/batch numeric | Performance-only nếu weights, records, math và decision-sequence parity giữ nguyên |
| Exact evaluation reuse | Có điều kiện: cùng data/state/economics/purity; giữ logical trials và ask/tell behavior |
| Giảm trials, forward labels, origins, features hoặc cắt current candidate pool | **Research/policy change**, không optimization tương đương |
| Coarsen params, gộp near-duplicates, nén approximate descriptors | **Thay search/model**, không lossless optimization |
| Bật pruning/early stopping mới; đổi adaptive sequential thành batch | **Thay stopping/proposal process**, cần version/budget/evaluation riêng |
| Đổi scorer precision, event semantics, sizing hoặc metric | Không chấp nhận như performance-only; giữ existing financial contract |

Full eligible current pool không bù được labels lịch sử đã bị cắt. Profile đã chọn temporal/plateau descriptors thì không bỏ chúng để dùng một fast scorer thiếu fields: dùng supported adapter hoặc báo capability limitation. Không cắt label controls/history để đạt SLA rồi claim meta không mất insight.

Nếu budget không đủ, báo trước bulk run và xin điều chỉnh study; không tự làm nhẹ bài toán. Tính năng thư viện vẫn cho caller cấu hình budgets hợp lệ, nhưng giữa reference và optimized benchmark phải giữ budgets/policies giống nhau.

### 10.1. Đo cost components, không tối ưu theo cảm giác

Mỗi benchmark instrument riêng:

\[
T_{total}=T_{plan}+T_{prepare}+T_{ask/tell}+T_{IS-score}+T_{native-select}
+T_{history}+T_{meta-fit}+T_{meta-rank}+T_{label-observer}+T_{OOS}+T_{report}.
\]

Labels là chi phí thật có thể lớn hơn Ridge rất nhiều. Không so run meta có thêm16 forward evaluations với native không có evaluations ấy rồi quy toàn overhead cho matrix multiply; cũng không loại label work để nói meta gần như miễn phí.

Ghi cả:

```text
logical trial count / physical evaluator calls
logical candidate analyses / actual score bars
prepared cache hit/miss / owned bytes / copied bytes
PyO3 calls / Python callbacks nếu available
wall, CPU, peak RSS/PSS theo phương pháp rõ
native/Numba/Python resolved route và reason
```

Không dùng bar-volume khác nhau trong hai mẫu để gọi throughput win.

### 10.2. Các tối ưu thuộc scope và thứ tự ưu tiên

| Ưu tiên | Tối ưu | Gate correctness |
|---|---|---|
| P0 | Prepare fold calendars/shards/current IS view một lần, reuse existing caches | Không giữ future view trong scorer-facing object |
| P0 | Feature matrix pool một lần, columnar rather than loops/DataFrames mỗi candidate | Same feature values/order/schema |
| P0 | Không dựng NxN W; solve hệ d×d | Reference Ridge parity |
| P0 | Index archive theo compatibility + available_at; incremental prefix view | Same records/weights như full scan |
| P1 | Cache model fit theo exact snapshot/basis/λ; không refit cho mỗi candidate | Same β/support/provenance |
| P1 | Post-selection exact evaluation reuse qua existing evaluator policy | Native logical records/RNG đúng |
| P1 | Compact metrics/paths cần thiết, selected audit qua existing report route | Không đổi accounting; không fabricate missing raw evidence |
| P0 design / measured execution | Rust-first batched transforms, Gram accumulation và score/guard reduction; NumPy/Numba khi không phù hợp có lý do | GIL/lifetime, fit/decision-sequence parity và whole-stage cost; không silent fallback |
| Deferred | Covariance warm-start transfer, adaptive sampler allocation, parallel ask/tell redesign | Ngoài V1 |

### 10.3. Sufficient statistics và changing basis

Nếu descriptor transform giữ cố định, có thể update \(G_{data}=\sum wvv^\top\), \(b=\sum wvY\) bằng new matured task blocks.

Nếu scaler/category schema/weights thay, không cộng new rows vào old G một cách mù. Với small d, recompute từ compact historical descriptor matrix thường đơn giản và an toàn hơn một transform algebra phức tạp. Sliding-history removal cần subtract đúng origin weights và revalidate SPD.

Đây là tối ưu sau parity reference, không prerequisite để có feature hoạt động. Late-label revision phải tuân §6.8: thay cả origin contribution vì mẫu số M_k thay; không chỉ append. Mỗi cached contribution có task/revision/basis/weight-policy key. Không thêm một công thức cập nhật basis nâng cao ngoài phạm vi đã duyệt trong V1.1.

### 10.3.1. DSA tối ưu trong phạm vi module

- Index theo compatibility family/corpus và sorted revision availability; as-of lookup dùng binary search hoặc monotone cursor ở chronological lane, không full-scan unrestricted store mỗi fold. Cursor chỉ dùng tiến thời gian; replay lùi/resume snapshot khác phải resolve lại exact versions.
- Immutable task versions và dictionary keyed canonical IDs để dedup/anchor lookup; native iteration/hash order không được quyết định tie winner. Physical eval reuse không xóa logical candidate roles.
- Blocked/contiguous arrays và workspace reuse với memory budget rõ. Sparse categorical storage chỉ dùng khi cho đúng kết quả/reference và thật sự tiết kiệm; không feature hashing hay cắt categories để giảm d.
- Tính Gram/b theo chunks để memory không tăng như N². d tăng thì preflight workspace, sparse/dense choice và chi phí d²/d³; thiếu memory là resource issue, không được lén giảm chiều model.
- Winner reduction hai pass theo §8.5; complete rankings chỉ sort/materialize khi output contract yêu cầu. Giữ đủ numeric predictions/IDs để tái dựng report mà không gọi engine.
- Fit-cache theo exact snapshot/basis/λ, không chỉ cutoff hay params. Bounded caches có eviction không ảnh hưởng scientific records; working-buffer eviction khác việc xóa lịch sử học.
- Tránh nested Rayon/BLAS/Numba thread pools vượt quota. Parallel work chỉ trên immutable independent numeric/evaluation blocks đã được existing runtime chấp nhận; deterministic results và charging vẫn giữ.

### 10.4. Parallelism giữ methodology

- Default `n_jobs` theo native 1.1.1 config; nếu existing generic optimizer yêu cầu1 thì không nới bằng PR này.
- Adaptive TPE/MTPE/CMA sequence giữ ask/evaluate/tell order đã khai báo.
- Có thể parallel independent studies hoặc fixed post-freeze label evaluations khi existing evaluator isolation và memory budget cho phép.
- Không parallel chronological decisions khi downstream meta cần outcomes/model snapshots chưa đúng thứ tự.
- Cap BLAS/native threads theo process budget, tránh workers×threads oversubscription.
- Copy-on-write/read-only prepared data không có nghĩa callbacks mutable được share an toàn.

Optuna đã tối ưu sampler internals; trước hết đo actual ask/tell cost. Không rewrite TPE/CMA-ES hoặc gọi Rust cho từng scalar suggestion để tiết kiệm một overhead chưa được đo [S4].

### 10.5. Benchmark recipes công bằng

Tách hai benchmark modes:

**Replay-fixed-pool benchmark:** cùng candidate set và histories, đo prepare/meta/ranking/bridge overhead/parity. Dùng để đánh giá implementation nhanh hơn.

**End-to-end sampler study:** proposal trajectories khác nhau, cùng data/budget/native objective; đo elapsed/cost và outcomes. Đây là algorithm comparison, không exact speedup oracle.

Không gọi Sobol fixed batch nhanh hơn sequential TPE là “TPE được tối ưu X lần” vì nó đổi quá trình tìm kiếm.

Với equal-geometry fixture, kiểm continuous correlated, bounded integer, mixed categorical/conditional và invalid-constraint cases. Synthetic fixtures chứng minh behavior/capability, không economic edge.

### 10.6. Acceptance thresholds về performance

Trước patch, QMS-01 đo baseline để freeze budgets phù hợp host. Không hứa một absolute time mà chưa benchmark.

Working targets để maintainer phê duyệt trước measurements cuối:

- Disabled: zero new evaluations và same exact selected/metric outputs; overhead time p50 không quá3%, p95 không quá5% khi noise đủ thấp để đo. Nếu baseline quá ngắn/noisy, dùng repeated aggregate method đã đăng ký, không chọn repeat đẹp.
- Memory disabled: không có growth theo folds do module; import/lazy allocation behavior được đo.
- Meta fit/rank benchmark: report `(N,d,P)`, calls/allocations và Rust-first resolution theo block; đo conversion/FFI/JIT/cold-warm cost và so NumPy/Numba reference. Không đặt arbitrary ×10 target.
- Optimized meta path phải nhanh hơn hoặc giảm memory trên cùng contract so với module reference ở representative workload; không thể hiện lợi ích thì không promote optimization, giữ reference.
- End-to-end report phải bao gồm extra label cost; không dùng thời gian solver thay thời gian nghiên cứu.

Các mốc3%/5% là proposal acceptance defaults của tài liệu, không kết quả đã đạt hoặc yêu cầu platform-generic cứng. Thay ngưỡng cần decision trước benchmark outcomes.

### 10.7. Compute budget nghiên cứu tích hợp

Public library không ép mọi user chạy >=128 trials hoặc12 folds; fixtures nhỏ vẫn hợp lệ.

Để có **economic acceptance study** theo yêu cầu đã trao đổi: >=128 attempted trials/cutoff, >=12 matured meta origins trước evaluated development và >=12 paired-valid evaluation folds trên một cell đã đăng ký. Source correctness và library release không được fake những counts này nếu chưa chạy.

Module integration mặc định chỉ yêu cầu một primary real-alpha cell BTC và một mixed-schema technical fixture; không mở lại mọi alpha/symbol. Có thể thêm một HMA actual case nếu owner cần kiểm mixed params, nhưng không tự coi mọi con số cũ comparable do budgets khác nhau.

Tối đa hai sampler recipes được chọn **trước OOS outcomes** cho matched economic comparison; bốn recipes đều có engineering/capability tests. Nếu muốn thử đủ bốn economic paths, ghi budget riêng trước outcomes, không giả đó là chi phí bắt buộc của một module nhỏ.

<a id="s11"></a>
## 11. Tám phase triển khai và exit gates

### Bản đồ phases

| Phase | Đầu ra trọng tâm | Thứ không mở thêm |
|---|---|---|
| QMS-01 | Pin1.1.1, trace seams, baseline và scope/compatibility map | Không redesign toàn repo |
| QMS-02 | Bốn sampler recipes dùng factory hiện có; schema/mixed-space bridge | Không rewrite Optuna |
| QMS-03 | Meta records/history view/descriptors/causal label observer | Không tạo database/service |
| QMS-04 | Weighted Ridge, Rust-first numeric path/reference, min-Y guard và artifacts | Không thêm model zoo |
| QMS-05 | Actual Mode4/per-fold-causal integration off/shadow/active | Không sửa modes1/2/3/5 để meta chạy |
| QMS-06 | Prepared/native route adapter và host decision handoff | Không xây financial/live controller |
| QMS-07 | DSA/Rust-first optimization, measured fallback và parity xuyên folds | Không giảm information budget hoặc đổi phương pháp |
| QMS-08 | Regression, bounded empirical validation, docs/wheel/handoff | Không bật meta default hoặc tự deploy |

QMS-01…08 là implementation sequence. Không cần mỗi phase đều chạy một market study lớn. Negative economic result không làm mất technical work đã đạt; missing required test/capability thì chưa được đóng scope đó.

---

### QMS-01 — Xác minh đúng source 1.1.1 và điểm nối

**Mục tiêu:** thay vì một guide generic, agent xác định exact functions trong source/wheel đang nâng cấp và lập patch boundary có thể review.

**Input:** release metadata §0, current repository, existing tests/docs, audit bundle chỉ làm lessons learned.

**Công việc:**

1. Ghi `git rev-parse HEAD`, branch, dirty diff, allowed branch/worktree; đọc `pyproject.toml`, lockfiles, native manifest và import origins trong isolated env. Không sửa environment production.
2. Đối chiếu tag/commit và distribution metadata với §0; ghi các khác biệt approved working tree so với release. Không tự downgrade working tree hoặc reset.
3. Đọc nguyên các functions/branches liên quan: endpoint/config, `_run_per_fold_schedule`, `optimize_params`, native selection/sampler/retention/OOS scoring và existing claims/clocks. Map cutoff, completion, seal/effective fields theo §6.3; lưu exact symbol ranges/hashes, không chỉ grep tên.
4. Trace một minimal public Mode4 causal call với spy/call counters để xác định `native anchor`, `full eligible IS pool`, `meta hook location`, `outcome observation seam` và retention sources. Chưa thêm meta logic.
5. Đọc actual Rust/prepared adapter cùng capability guard. Ghi scalar/W0/static/W3 support theo tag, không theo README mới hơn.
6. Chạy baseline small fixture cho valid modes/schedules và một representative real strategy đã có. Lưu native params/trials/objectives/route/raw outputs cần cho parity, cùng wall/RSS.
7. Freeze file allowlist, sampler roster, endpoint schema, Rust-first numeric boundaries và information-preservation contract §10.0. Mọi financial defect có reproducer riêng; chỉ route đáp ứng mới được hỗ trợ, không viết financial subsystem để vượt gate.
8. Tạo `SOURCE_AND_SEAM_MAP.md` và `legacy_baseline_manifest.json`, owner review trước code mới.

**Tests/checks bắt buộc:**

| ID | Expected |
|---|---|
| Q1-T01 | Tag/distribution/import mismatch bị phát hiện; không đọc root mirror thay `src/quantbt` |
| Q1-T02 | Public Mode4 causal không dùng current outer OOS; map data cutoff khác completion/seal/effective; search sau cutoff không bị backdate hoặc reject sai |
| Q1-T03 | Native selected khác raw-best khi fixture yêu cầu; map đúng anchor |
| Q1-T04 | Full eligible pool cardinality/IDs có nguồn; filtered `fold_candidates` không bị nhầm |
| Q1-T05 | Trace prepared scorer timing/route và guards đúng installed capability |
| Q1-T06 | Existing valid mode/schedule baseline records đầy đủ, unsupported baseline behavior giữ nguyên |
| Q1-T07 | Protected financial files/source hashes và existing dirty state được lưu |
| Q1-T08 | Baseline payload/resource thật; khóa information budget và Rust-first/fallback scope trước performance comparison |

**Exit gates:** `G1-SOURCE`, `G1-SEAMS`, `G1-BASELINE`, `G1-SCOPE`, `G1-OWNER`.

`G1-SOURCE` phải có actual host source hashes. Các trích đoạn trong guide giúp định hướng nhưng không tự làm gate này PASS. Nếu không có baseline source, vẫn có thể review spec nhưng chưa được triển khai như đã pin.

---

### QMS-02 — Sampler config bridge và parameter-space correctness

**Mục tiêu:** user chọn sampler tại WFO mà native methodology vẫn giữ nguyên; mixed-space semantics có diagnostics.

**Công việc:**

1. Reuse `SamplerConfig`/factory hiện có. Bổ sung WFO config plumbing và resolver bốn recipes; giữ no-config path tạo sampler như baseline.
2. Map multi-stage WFO study seeds/stages đúng. Mode1two-stage hoặc Mode2proxy không được flatten thành một generic study khác.
3. Thêm space compatibility preflight, joint/independent dimension report, categorical/conditional effective-param identity và formal constraint policy.
4. Implement new recipes bằng installed Optuna/cmaes, no monkeypatch/private optimizer reimplementation. Dependency missing được báo trước first evaluation.
5. Seed/fold/stage derivation giữ đúng legacy; new diagnostics dùng RNG stream riêng hoặc không RNG. Snapshot sampler state trong supported persistence path.
6. Nối param-only warm-start opt-in với existing current evaluator. Không import old objective values. Cấm double warm-start bổ sung ngoài budget.
7. Chạy small synthetic fixtures: correlated numeric ridge, integer bounds, unordered categories, conditional branch và constraints. Đo early-reject work; verify stopping/ask-tell behavior không đổi trong performance-only lane, warm-start không làm same-pool arms diverge.
8. Sampler-only regression qua valid methodology matrix; meta vẫn off. Không cần benchmark economics mỗi mode ở phase này.

**Tests:**

| ID | Expected |
|---|---|
| Q2-T01 | Omitted sampler config khớp legacy proposals, objectives, selected params và seed trace |
| Q2-T02 | TPE group actual object/kwargs đúng; group=True thiếu multivariate bị reject |
| Q2-T03 | CMA unsupported categorical default fail; explicit independent config có metadata truthful |
| Q2-T04 | Integer/log/step/conditional mapping đúng; inactive differences không tạo effective candidate giả |
| Q2-T05 | Sobol sequence/startup/scramble/resume position đúng; không gọi total128 là128 pure QMC khi không đúng |
| Q2-T06 | Constraints early rejects không thành successful score, formal post-filter được enforce |
| Q2-T07 | Warm-start current-score/availability/budget đúng; no stale scores; selector-only arms giữ canonical same seed pool |
| Q2-T08 | Actual supported mode stages giữ scorer/native selection; unsupported combo fail trước financial work |

**Exit gates:** `G2-SAMPLER4`, `G2-SPACE`, `G2-LEGACY`, `G2-REPRODUCIBILITY`, `G2-COST`, `G2-OWNER`.

Không bắt mọi sampler thắng objective để technical PASS. Missing optional cmaes dependency chưa cài vì quyền thì scope đó `NOT_IMPLEMENTED_CAPABILITY`, không gọi full four-recipe delivery hoàn tất.

---

### QMS-03 — History/descriptors/labels đúng task và thời gian

**Mục tiêu:** tạo nguồn học có thể kiểm chứng và không lặp lỗi STATIC anchor/stale descriptors.

**Công việc:**

1. Implement/reuse compact records và ba identities §6.5: task, compatibility family, training snapshot. Explicit anchor; fold seed/date không làm family tách vụn; same family không tự authorize mọi corpus.
2. Implement schema-driven descriptors, one-hot categories, inactive masks, weighted numeric standardizer và read-only current pool view.
3. Implement as-of index và typed validation; seal/revision theo §6.8, exact task-version selection, weight replacement khi late labels. Model chỉ nhận permitted immutable snapshot, không unrestricted store.
4. Implement post-decision observer adapter sử dụng **existing** candidate evaluation/result extraction. Forward metrics và actual base equity/date boundary có refs đầy đủ; không tạo metric calculator tài chính mới.
5. Panel quotas/diversity/anchor+winner union đóng băng trước forward reveal. Metadata đầy đủ cho outputs nonselected, kể cả failed.
6. Imported bundle records phải qua provenance/maturity/anchor validator. Affected old labels không được trusted chỉ vì CSV khớp; giữ as unverified hoặc rebuild affected via existing evaluator trong scope được duyệt.
7. Safe serialization và semantic cache IDs. In-memory provider và một adapter vào existing persistence đủ cho V1; không mở backend service.
8. Kiểm observer replay small history bằng fake market-independent labels cho unit tests và một actual engine-produced label để xác nhận integration semantics.

**Tests:**

| ID | Expected |
|---|---|
| Q3-T01 | Hai candidate roles/STATIC đứng đầu không đổi explicit anchor; missing/duplicate anchor fail |
| Q3-T02 | Label Y/Q identities và same-origin/current-IS metadata được kiểm bằng actual records |
| Q3-T03 | Future/unmatured/revision-unavailable records bị chặn; labels xuất hiện trong thời gian compute không lọt snapshot đã khóa; computation sau cutoff vẫn hợp lệ |
| Q3-T04 | Categorical permutation/conditional masks đúng; unknown/schema shape mismatch fail, không pad/reset |
| Q3-T05 | HMA-like different keys tạo diversity distances thật, không default sang ASC keys |
| Q3-T06 | Failed/no-variance/censored outcomes không thành valid numeric training label |
| Q3-T07 | Incompatible sources/contracts không pool; valid folds khác date/seed ghép cùng family, corpus permission vẫn chặn run khác |
| Q3-T08 | Roundtrip/pending maturity/seal/hash đúng; late labels tạo revision mới, mỗi task một contribution, earlier snapshots không đổi |

**Exit gates:** `G3-TASK`, `G3-CAUSALITY`, `G3-DESCRIPTORS`, `G3-LABELS`, `G3-PORTABLE_HISTORY`, `G3-OWNER`.

Nếu canonical evaluator thiếu information để xác nhận finite Sharpe contract, block affected meta-label lane, không sửa global metrics từ module này.

---

### QMS-04 — Ridge reference, ranking và decision artifacts

**Mục tiêu:** model nhỏ, deterministic, dùng đúng mathematical target và không để guard biến thành một rule khác.

**Công việc:**

1. Implement `ridge_origin_sum_v1` và reference numerics đúng objective; Rust-first cho blocks mới qua existing native crate, NumPy/Numba fallback có lý do. Giữ λ/fit-mask/weights/transforms trong artifact, không đổi learner vì backend.
2. Accumulate G/b không N×N W; `solve`/Cholesky với error handling cụ thể; residual/conditioning diagnostics dùng ở debug/report, không tạo false certainty.
3. Implement batch scoring, Q guard, total-order tie rule, native cold-start fallback và strict invalid-input behavior.
4. Preserve anchor contrast0, current pool independent future labels, native-best/native-selected/meta-proposed distinction.
5. Safe model bundle export/import, dependency digests và basis compatibility.
6. Implement optional shadow outputs nhưng chưa gắn vào full WFO loop. Không copy entire lab `selector.py` có unused H14/O/placebo branches.
7. Viết mathematical fixtures, including target coupling and lambda normalization. Không đưa empirical beta2.11 như parameter mặc định.
8. Profile fixed-matrix fit/rank, đo Rust batch và reference/fallback gồm conversion/dispatch; ghi block resolution. QMS-07 tối ưu thêm, không đợi tới phase đó mới cân nhắc Rust hoặc chấp nhận production Python loops không lý do.

**Tests:**

| ID | Expected |
|---|---|
| Q4-T01 | G/b solve khớp explicit weighted reference, no dense N×N allocation |
| Q4-T02 | Anchor v/Yhat/Qhat bằng0; list reorder không đổi model/ranking trong tolerance |
| Q4-T03 | Origin weight không bị candidate count chi phối; task từ1 lên10 labels phải reweight toàn origin; revision/duplicate không tăng support giả |
| Q4-T04 | Fixture §5.7 chọn y; minY khác maxIS và guard reject z |
| Q4-T05 | λ/basis versions đúng; Rust/NumPy/Numba active blocks cùng math, β units/snapshots tái lập; backend metadata không giả native |
| Q4-T06 | NaN/Inf/empty safe pool/unknown ID không thành selected success |
| Q4-T07 | Historical labels mới chưa mature không đổi fit; current labels bị xóa vẫn predict được |
| Q4-T08 | Restore model/scaler/categories/params → same scores/winner; missing scaler fail |

**Exit gates:** `G4-MATH`, `G4-POLICY`, `G4-SERIALIZATION`, `G4-SUPPORT`, `G4-RESOURCE`, `G4-OWNER`.

No-skill chưa thể kết luận ở phase này. Tests validate policy, không chứng minh superiority của Ridge. `G4-RESOURCE` ghi Rust-first block plan/implementation và mọi NumPy/Numba fallback, không chỉ một NumPy timing.

---

### QMS-05 — Gắn vào actual Mode 4 `per_fold_causal`

**Mục tiêu:** module thật sự được public endpoint gọi tại seam đã xác định, trước existing final fold params.

**Công việc:**

1. Thêm normalized configs và runtime history binding. Không bắt user import lab repo hoặc sửa alpha để chạy module.
2. Chèn hook sau native selection/baseline floor, trước `params_by_fold` và current OOS strategy execution. Hoặc successor seam verified trong QMS-01.
3. Preserve native record immutable; selected candidate có current IS/task lineage. Existing result adaptation ghi native/final-policy scopes và actual historical-forward usage theo §2.5, cùng information_as_of/completion/seal clocks; không backdate.
4. Gắn as-of observer acquisition; kiểm outcome order không ảnh hưởng same-fold selection. Không bật evaluate current OOS ở native optimizer.
5. Endpoint rejects unsupported mode/schedule/route khi shadow/active; khi off dùng path cũ. Sampler-only independent.
6. Enforce shadow account parity và active forced-switch fixture; prove không có downstream IS floor overwrite. Verify final-policy metadata ở active-same-anchor, fallback và shadow không bị suy từ enabled flag.
7. Reuse existing fold-account policy, fees/timing/strategy lifecycle, retention flags. Added records thuộc research sidecar; không bắt financial audit full cho mọi trial.
8. Tạo executable public example sau implementation và test nó, không chỉ pseudocode. Giữ one existing real strategy demo, không chép alpha source vào core package.

**Tests:**

| ID | Expected |
|---|---|
| Q5-T01 | Meta off byte/value-equivalent legacy outputs và zero archive/auxiliary calls |
| Q5-T02 | Shadow search/native params/orders/result giống baseline; diagnostics riêng có provenance |
| Q5-T03 | Active fixture tạo winner khác native và existing output path dùng đúng winner đó |
| Q5-T04 | Lower-IS eligible meta winner không bị downstream baseline floor ghi đè |
| Q5-T05 | Unsupported meta fail trước optimizer; native Mode4 và final meta scopes đúng ở active/same-anchor/cold-start/shadow, không sửa mode |
| Q5-T06 | Actual spy/future mutation giữ prefix; snapshot00:00/search00:08/seal00:09/effective00:15 hợp lệ, 00:05 new label bị chặn, no backdating |
| Q5-T07 | Post-decision labels chỉ ảnh hưởng later eligible folds; INIT/support fallback thật |
| Q5-T08 | Raw trial/best/native/meta fields và chosen params reconcile; result consumers cũ vẫn dùng được |

**Exit gates:** `G5-ENDPOINT`, `G5-MODE4_CAUSAL`, `G5-LEGACY`, `G5-ACTUAL_SELECTION`, `G5-OBSERVATION`, `G5-OWNER`.

Đây là phase chứng minh không có “helper đúng nhưng runner bỏ qua”. `G5-MODE4_CAUSAL` bao gồm đúng input frontier/completion clocks và final-selector information metadata. Không đóng phase chỉ bằng unit tests của Ridge.

---

### QMS-06 — Prepared route adapter và handoff dùng được bởi host

**Mục tiêu:** cùng mathematical policy hoạt động qua scoring routes đã có; runtime meta Rust-first và qualified NumPy/Numba fallback dùng cùng contract, không một selection logic riêng cho live.

**Công việc:**

1. Run same fixed pools qua existing reference và prepared-native scorer đúng capability; compare raw metrics/decisions theo route parity policy.
2. Reuse run-local prepared market/calendars/subperiod views. Không dùng optimizer trial caching trái exact-analysis contract.
3. Prove meta không tăng callbacks theo bars; fit/rank boundaries theo task/fold, không per-bar.
4. Giữ `native_prepared_wfo=off/auto/require` và prepared strategy policies. Unsupported timing/unit/fee/runtime path fail/fallback đúng existing convention.
5. Đánh giá separate W3 adapter bằng scope gate. Chỉ implement nếu reuse selection seam và existing outputs; nếu cần rewrite scheduler/financial model thì document deferred, không mở scope.
6. Export `MetaSelectionDecision`/model bundle và một pure as-of selection example cho existing host. Không tạo HTTP server/queue/deployment controller.
7. Restore/replay exact model/basis/corpus/task revisions; export cutoff/completion/seal/ready/effective refs theo §6.3/§9.2. Existing host owns actual activation và pending orders; module không sửa clocks để giả live parity.
8. Update endpoint capability docs: scalar/prepared supported, W3 support/deferred, native artifact requirements, no automatic live permission.

**Tests:**

| ID | Expected |
|---|---|
| Q6-T01 | Reference/prepared same contract cho same pool → same native/meta selection trong declared tolerance |
| Q6-T02 | Same-close route không giả next-open; incompatible route/timing được reject |
| Q6-T03 | `require` missing/unsupported native fail; meta không đổi global backend auto |
| Q6-T04 | Prepared data/buffers ownership, no cross-run mutable state hoặc stale view |
| Q6-T05 | Model inference/callback counts theo folds/pools, không theo bars |
| Q6-T06 | Export/restore giữ model/params/corpus/task revisions và distinct clocks; current model không được replay vào past, actual late effect không ghi foldstart |
| Q6-T07 | Consumer handoff không gọi broker/account mutation; same-params decision không tự reset state |
| Q6-T08 | W3 enabled có explicit route test; deferred thì config fail rõ, không success metadata giả |

**Exit gates:** `G6-ADAPTER`, `G6-PREPARED_PARITY`, `G6-CAPABILITY`, `G6-HANDOFF`, `G6-NO_SCOPE_CREEP`, `G6-OWNER`.

W3 có thể deferred mà scalar module hoàn tất nếu phạm vi đó đã duyệt trước. Không claim meta dùng được cho mọi reactive alpha khi chỉ scalar path được test.

---

### QMS-07 — Rust-first, DSA tối ưu và parity xuyên folds

**Mục tiêu:** giảm chi phí phần mới và tận dụng scorer hiện có, không đổi algorithm để lấy bảng benchmark đẹp.

**Công việc:**

1. Profile components §10 trên baseline, reference meta và optimized meta. Nhận diện prepared/copy/retention/historical lookup hotspots trước sampler internals.
2. Tối ưu DSA §10.3.1: contiguous/columnar buffers, as-of revision indices, per-origin contributions và fit cache, linear winner reduction. Giữ full pool, panel/profile/history/precision; không đổi stopping hay logical trial budget.
3. Benchmark scales N/d/P phù hợp small A-SC và mixed-dimensional fixture; không chỉ một tiny case để tuyên bố universal.
4. Hoàn thiện/profile Rust-first batch kernels đã thiết kế ở QMS-04/06; ghi conversion/dispatch/native time và fallback NumPy/Numba theo block khi không phù hợp. Numba cold JIT và warm execution tách rõ; kernel không financial inputs.
5. Validate near-boundary fit/rank và full chronological sequence parity, có late-task revision/resume; reference fallback đủ phạm vi khi error bound không rõ. Không promote speedup làm lệch decisions; nếu Rust không phù hợp ghi measured fallback, không nới tolerance.
6. Không thay TPE sequential thành batch/parallel, không sửa Mode2 bootstrap RNG, không suppress categorical warnings để giải thích perf.
7. Đo disabled overhead, memory plateau, warm/cold provenance và existing callback counts. Chạy alternating paired processes khi cần giảm noise.
8. Ghi optimization ledger: thay gì, giảm phần nào, chi phí thêm labels, không nhân speedup các stages thành one-number marketing.

**Tests:**

| ID | Expected |
|---|---|
| Q7-T01 | Rust-first và reference/fallback cùng scores trong tolerance, eligible/tie sets/params/history decisions khớp qua nhiều chronological folds |
| Q7-T02 | Near Q-floor/tie ở early fold không đổi later trajectory; uncertainty của fast numerics dùng reference đủ phạm vi, không chỉ so allclose β |
| Q7-T03 | Chunk/index/cache/resume giữ exact task revisions/weights/frontier; late revisions replace không append kép, observer không mutate main RNG/state |
| Q7-T04 | No dense weight matrix, allocations/RSS/PSS measured và bounded theo retained data |
| Q7-T05 | Rust-first resolution/capability và GIL/buffers đúng; fallback NumPy/Numba có reason, nopython/JIT costs và same precision; require thiếu native fail |
| Q7-T06 | Sampler ask/tell trace unchanged trong exact-parity lanes |
| Q7-T07 | Same information/work: không giảm trials/labels/features/history/pool/precision hoặc đổi pruning; charge I/O/FFI/JIT, no cache deception |
| Q7-T08 | Disabled overhead target đạt hoặc regression blocker rõ; no fabricated speedup |

**Exit gates:** `G7-PARITY`, `G7-COST_ACCOUNTING`, `G7-MEMORY`, `G7-DISABLED_OVERHEAD`, `G7-PERF_DISPOSITION`, `G7-OWNER`.

`G7-PARITY` bắt buộc chronological sequence parity và exact information membership theo §8.6.1/§10.0. `G7-PERF_DISPOSITION` phải có Rust-first design/measurement, selected execution blocks và lý do NumPy/Numba nếu dùng; không nghiệm thu “nhanh hơn” bằng việc co bài toán.

Rust-first là yêu cầu thiết kế và xét execution path đầu tiên. NumPy/Numba được chấp nhận khi một block Rust không phù hợp và có evidence/reason, không phải lý do bỏ việc thiết kế DSA/native path. Không có nghĩa bắt Rust thắng mọi tiny matrix hoặc thêm financial rewrite. Acceptance yêu cầu fidelity và sequential parity, legacy không regression vượt ngưỡng, có measured costs; module không hứa overall speedup khi làm thêm công việc học/labels.

---

### QMS-08 — Regression, bounded economic study, tài liệu và đóng gói

**Mục tiêu:** phát hành một opt-in capability có spec đúng và evidence đủ, không phát hành lời hứa mọi strategy tốt hơn.

**Công việc:**

1. Chạy compatibility matrix five modes + supported schedules với meta off; fixed backtest và public result serialization không bị đổi. Param sampler-only lanes theo capability đã triển khai.
2. Chạy end-to-end new feature matrix: cold start, imported history, task revision, shadow/active, Rust-first/reference/fallback, missing capability và methodology errors; bắt buộc sequence parity trên nhiều folds với exact snapshots.
3. Một bounded real-alpha study theo registration riêng: common current pools, native vs meta, đủ matured history trước >=12 paired-valid final folds; >=128 attempted trials/cutoff trong scientific lane. Không ép 128 cho unit tests.
4. Nếu so sampler economic, giữ same budget/window/objective/seed protocol; không trộn source32 với64trials rồi claim optimizer superiority. Tối đa roster đã duyệt.
5. Report mean-fold decay + IS/FWD decomposition, final-policy information scope và existing whole-account metrics nếu route cung cấp; reset-segment chỉ report đúng loại. Không gọi meta final decision là stock IS-only hoặc tạo portfolio curve mới.
6. Counterfactual labels/reference outputs có source status đầy đủ; old invalid labels không được dùng để tạo apparent success. Actual negative/low precision được giữ.
7. Viết docs và examples chạy được: disabled legacy, sampler-only, causal meta với local history, unsupported combinations, native policies, host handoff. Mẫu endpoint mới phải được integration-tested.
8. Build wheel từ clean allowed branch; verify install/import extras/core-native matrix. Core version mới do Bobby chốt; không ghi đè v1.1.1. Scoped PR, báo technical vs empirical status riêng.

**Tests:**

| ID | Expected |
|---|---|
| Q8-T01 | Legacy five-mode/schedule/result regression pass trên baseline matrix thực |
| Q8-T02 | Public examples/schema phản ánh rust_first và five approved clarifications; unsupported/require/fallback codes đúng docs |
| Q8-T03 | Real-alpha chosen candidate lineage từ native pool qua meta tới existing run output |
| Q8-T04 | Empirical fold/trial/maturity counts actual hoặc `NOT_RUN_BUDGET/INCOMPLETE`, không fake PASS |
| Q8-T05 | Raw scores/decomposition và final-policy scopes đúng; full sequence/model/task revision trace tái lập; no undefined→zero/date compression |
| Q8-T06 | Tampered payload/model/scalar/complete flag làm independent verifier fail |
| Q8-T07 | Wheel source/import/dependency/native capability và disabled-no-extra-dependency behavior đúng |
| Q8-T08 | Report regeneration không gọi engine/inference; branch/protected diffs và owner approval rõ |

**Exit gates:** `G8-REGRESSION`, `G8-END_TO_END`, `G8-EMPIRICAL_SCOPE`, `G8-DOCS`, `G8-PACKAGE`, `G8-OWNER`.

`G8-EMPIRICAL_SCOPE` có thể ghi valid no-gain hoặc low precision. Nếu market run chưa được cấp budget, ghi `SOFTWARE_CANDIDATE_READY / EMPIRICAL_VALIDATION_NOT_RUN`, không gọi toàn planned scientific study complete. Feature không tự thành default chỉ vì một cell dương.

<a id="s12"></a>
## 12. Rules báo cáo, verifier và upgrade discipline

### 12.1. Mỗi phase có bốn trạng thái riêng

```text
implementation_status: NOT_STARTED | RUNNING | COMPLETE | BLOCKED
technical_gate: NOT_RUN | PASS | FAIL | BLOCKED
empirical_status: NOT_ASSESSED | NOT_RUN | INCONCLUSIVE | SCOPED_GAIN | SCOPED_NO_GAIN
owner_review: PENDING | APPROVED | CHANGES_REQUESTED
```

Performance là một phần evidence riêng có `MEASURED / NOT_MEASURED / REGRESSION / NOT_PROMOTED`; không lấy empirical gain che numerical hoặc compatibility failure.

### 12.2. Một report sau mọi run/upgrade, kể cả thất bại

```markdown
# QMS Phase/Run Report — <phase/run_id>

## Source và scope
Baseline tag/wheel; actual commit/diff/module origin/native build.
Source/seam map version; files changed; protected files unchanged.
Requested mode/schedule/route/sampler/meta profile.

## Mục tiêu và actual work
Điều đã làm; điều chưa làm; exact commands và return/semantic status.
No financial subsystem added; unexpected dependency scope được tách rõ.

## Methodology và candidate identity
Native anchor/pool IDs, full-vs-panel count, current IS window.
History information frontier, corpus/family/task revisions, maturity và metric/basis/lambda.
Data cutoff, computation/seal/ready và existing effective-time refs; không backdate.
Native vs final policy/actual forward-history usage và actual downstream params.

## Tests/gates
| Gate/test | Expected | Actual | Evidence/hash | Status |
|---|---|---|---|---|
Executed tests, skips/missing capabilities và affected acceptance.

## Performance/resources
Same-pool parity hoặc different-sampler algorithm comparison?
Wall/CPU/peak memory, evaluator/bar/callback/FFI counts.
Native score time, Optuna overhead, history/fit/rank/label costs.
Rust-first requested/selected blocks, fallback reasons, FFI/copied bytes/JIT cost.
DSA, information-budget equality và chronological decision-sequence parity.
Cold/warm/cache conditions; resource allocation và remaining budget.

## Empirical results khi phase có chạy
Trials/folds, native/meta Sharpe, signed decay và decomposition.
Pairing/uncertainty/undefined status; reset-segment vs continuous route.
Không có market run thì không điền observed edge.

## Upgrade so với parent
Source/config diff, invalidated/reused dependencies, numerical changes.
Bugs được sửa không rewrite old records thành PASS.

## Quyết định tiếp
Technical/empirical/performance/owner status.
Một next authorized action; không tự mở thêm scope.
```

Tables sinh từ artifacts, không nhập tay các số summary khác CSV. `WFO_META_CURRENT.md` trong handoff/docs được cập nhật sau mỗi phase/run; tên này là đề xuất để map vào existing workflow, không một dịch vụ mới.

### 12.3. Artifact layout nhẹ

Reuse repository convention cho docs/tests/benchmarks. Logical structure:

```text
docs/meta_selection.md
examples/                       # theo existing examples layout
tests/.../meta_selection/        # actual pytest convention của repo
benchmarks/.../meta_selection/   # configs, manifests, small derived evidence
handoff/WFO_META_CURRENT.md
```

Raw large datasets/caches không đóng vào wheel hoặc commit không giới hạn. Evidence package có đủ verified references để reconstruct required result. Không chỉ giữ handwritten hash mà file đã biến mất.

### 12.4. Gate receipt mẫu chưa phải chứng nhận

```json
{
  "schema": "quantbt.meta_selection.gate.v1",
  "guide_version": "QMS-V1.1",
  "phase": "QMS-01",
  "baseline_release": "1.1.1",
  "baseline_commit_expected": "2c811a7faaed3c274e93c60650e16207949f0a59",
  "actual_source_manifest": null,
  "required_gate_registry_hash": null,
  "technical_gate": "NOT_RUN",
  "empirical_status": "NOT_ASSESSED",
  "tests": [],
  "evidence_refs": [],
  "open_blockers": [],
  "owner_review": {"status": "PENDING", "decision_ref": null},
  "can_start_next_phase": false
}
```

Verifier đọc required gates từ code/config độc lập, không tin receipt để `required_gates=[]` là hoàn tất. Check bytes/hash, boolean values, actual counts và required execution logs; một file có chữ PASS không đủ.

Finalize receipt trước detached seal. Source/config changes tạo version/claim update; không sửa receipt đã seal.

### 12.5. Upgrade classification

| Loại thay đổi | Nghĩa vụ |
|---|---|
| Docs/report correction | Recompute từ đủ outputs, không gọi engine vô ích |
| Sampler kwargs/seed/warmstart | New search identity; không reuse optimizer observations incompatible |
| Descriptor/target/anchor/λ normalization | New model/evidence version; invalidate labels/basis đúng phạm vi |
| History ingestion/late-label revision | Version task availability, replace full origin contribution, rebuild affected future snapshots/models; preserve earlier records |
| Performance refactor | Information-budget equality + fixed-pool và chronological sequence parity + measured Rust/fallback resources; no methodology drift |
| Existing financial dependency defect | Separate minimal issue/repair theo owner; chặn capability bị ảnh hưởng, không tự mở scope |
| Native ABI addition | Coordinated release pair/capability tests; không mutate published artifact |

### 12.6. Quy tắc vượt phase

Một phase chỉ advance khi tất cả gates bắt buộc của **scope đã duyệt** đạt và owner approval có reference thật. W3 có thể deferred theo scope đã duyệt; pure-meta Rust block không phù hợp phải có qualified NumPy/Numba disposition và lý do theo §8.5, không đánh dấu NOT_IN_SCOPE để bỏ chỉ đạo Rust-first. Không né mandatory scalar functionality hoặc required full-sequence tests.

Software completion không bắt buộc có edge dương. Scientific experiment chưa chạy hoặc dữ liệu không đủ thì report limitation; không dùng bug/timeout làm no-edge result, cũng không dùng no-edge result làm lý do refactor mãi.

<a id="s13"></a>
## 13. Cấu hình và ví dụ endpoint sau khi triển khai

### 13.1. Config tham chiếu — đặc tả mới, chưa là API của wheel1.1.1

```yaml
module:
  id: quantbt_meta_selection
  guide: QMS-V1.1
  baseline_core: 1.1.1
  baseline_native: 0.4.2
  default_enabled: false

wfo:
  optimization_mode: mode_4_is_only_robust
  optimization_schedule: per_fold_causal
  existing_calendar_and_execution_config: PRESERVE_CALLER_CONTRACT

sampler_config:
  name: tpe
  kwargs:
    multivariate: true
    group: true
  seed_policy: EXISTING_FOLD_AND_STAGE_SEED
  constraint_mode: EXISTING_COMPATIBLE_POLICY

meta_selection:
  mode: active
  learner: ridge_origin_sum_v1
  lambda_reg: 10.0
  selection_policy: relative_sharpe_decay_v1
  descriptor_profile: schema_params_is_sharpe_activity_v1
  descriptor_scaler: origin_balanced_zscore_v1
  min_matured_origins: 12
  q_hat_floor: -0.10
  tie_tolerance: 0.000001
  on_insufficient_history: native_selection
  on_schema_or_anchor_error: raise
  history_partition: exact_compatible_task_family
  history_corpus: EXPLICIT_ALLOWED_CORPUS_REFERENCE
  training_snapshot: sealed_task_revisions_as_of_input_cutoff
  late_label_policy: immutable_revision_replace_origin
  information_frontier: existing_data_cutoff
  decision_clock: runtime_completion_then_seal
  final_policy_metadata: actual_native_and_meta_information_scope
  current_outer_oos_read_allowed: false
  label_observer:
    enabled: true
    policy: anchor_balanced_panel_union_winners_v1
    base_panel_cap: 16
    evaluator: EXISTING_ROUTE_COMPATIBLE_EVALUATOR
    reporting_lag: EXPLICIT_CALLER_OR_REGISTERED_VALUE
  runtime:
    implementation: rust_first
    native_batch_policy: auto
    fallback_implementations: [numpy, numba]
    report_selected_backend_by_block: true
    require_fallback_reason: true
    numeric_dtype: float64
    fast_math: false
    parity_scope: chronological_decision_sequence

handoff:
  export_selection_decision: true
  start_service: false
  manage_orders_or_positions: false
  live_trading_authorized: false
```

`EXISTING_*` fields biểu diễn contracts phải resolve ở implementation, không được truyền literal này vào runtime. Dataclass/schema thực có thể rút gọn; intent phải giữ. `sampler_config.name=tpe` và kwargs trên là recipe đa biến; tpe legacy khi omitted phải giữ defaults thực baseline.

CMA-ES/Sobol examples chỉ dùng kwargs valid của pinned version. Module custom settings như `mixed_space_policy` thuộc QuantBT preflight, không truyền bừa vào constructor Optuna.

### 13.2. Public endpoint usage mong muốn

Pseudocode dưới cho biết vị trí config, không giả module đã phát hành:

```python
# Proposed usage AFTER implementation and API tests.
# strategy_class, existing_wfo_config, data, params and history are caller-owned.

optimization_config = {
    **existing_wfo_config,
    "sampler_config": {
        "name": "tpe",
        "kwargs": {"multivariate": True, "group": True},
    },
    "meta_selection": {
        "mode": "active",
        "learner": "ridge_origin_sum_v1",
        "lambda_reg": 10.0,
        "min_matured_origins": 12,
        "q_hat_floor": -0.10,
        "runtime": {
            "implementation": "rust_first",
            "native_batch_policy": "auto",
            "fallback_implementations": ["numpy", "numba"],
        },
    },
}

endpoint = QuantBTEndpoint.walk_forward(
    strategy_class=strategy_class,
    split_mode=existing_split_mode,
    split_frequency=existing_split_frequency,
    target_mode=existing_target_mode,
    window_mode=existing_window_mode,
    train_window=existing_train_window,
    optimization_mode="mode_4_is_only_robust",
    optimization_schedule="per_fold_causal",
    optimization_config=optimization_config,
    optuna_trials=128,
    random_seed=42,
    **existing_execution_kwargs,
)
# Binding runtime history uses the smallest existing run/context mechanism
# established in QMS-01. Do not hide a database URI/callable in serialized config.
# The implementation must publish and test the final exact invocation.
```

History injection được chọn một lần ở QMS-01: existing run context/typed provider hoặc keyword-only runtime handle có test. Không tạo một method name giả trong docs rồi yêu cầu downstream users dùng.

### 13.3. Result contract tối thiểu

Opt-in result metadata/sidecar giữ:

```text
fold_id, information_as_of/data_cutoff, completion/seal/ready/effective-time refs
mode, schedule, scorer/route; native vs final selection policy/information scope
current_outer_oos_used=false, actual past_matured_forward_used flags
sampler resolved config và search trace ref
native anchor candidate ID/params/native score
meta model ID/corpus/family/exact task-revision snapshot/support/status
requested/selected numeric backends by block, fallback reason và capability
candidate ranks, Yhat/Qhat và exclusion/guard reasons
meta proposed ID, actual selected ID/effective params
fallback, tie-break, current pool/descriptor digests
existing activation/params_by_fold linkage khi route expose
```

Raw native result/report APIs không thay shape mặc định. Export metadata chứa refs/compact arrays; không eagerly materialize toàn trial/fill table khi user chỉ lấy selected params.

### 13.4. Một lời gọi không hợp lệ phải nói rõ

Ví dụ requested:

```text
optimization_mode = mode_1_decay
optimization_schedule = per_fold_decay
meta_selection.mode = active
```

Expected logical response:

```text
META_METHODOLOGY_UNSUPPORTED:
Meta-selection V1 is certified only for mode_4_is_only_robust /
per_fold_causal on supported routes. The requested schedule may use
current outer-OOS results for native selection. No evaluation was started.
Disable meta to preserve the existing Mode 1 behavior, or explicitly select
a supported methodology. The endpoint will not change the mode automatically.
```

Message ngôn ngữ thực theo project convention. Không mắng user là strategy sai; đây là scope/methodology incompatibility.

<a id="s14"></a>
## 14. Đo hiệu quả module mà không mở lại cả regime lab

### 14.1. Những insight được kiểm chứng ở mức nào?

| Nhận định | Loại bằng chứng cần |
|---|---|
| Bốn sampler recipes chạy đúng | Space/constraints/seed/stage tests |
| Meta học đúng historical tasks | Anchor/maturity/basis/label tests |
| Meta đã tác động actual selection | Active-vs-native trace trên public WFO |
| Integration nhanh/nhẹ hơn bản reference | Same-pool/parity performance benchmark |
| Sampler A tốt hơn B trong một alpha | Matched-budget registered economic comparison |
| Meta giảm Sharpe decay có nội dung kinh tế | Paired outcomes + IS/FWD decomposition + uncertainty |
| Production live tốt hơn | Không thuộc certificate của module V1; cần existing deployment evaluation riêng |

### 14.2. Empirical acceptance study hữu hạn

Chốt trước outcomes:

- Một alpha/BTC cell đã chạy được qua **supported existing route**. Không đổi timeframe/instrument chỉ để dùng Rust.
- Cùng IS/FWD/calendar/economics giữa arms; lengths lấy từ registration có đủ coverage, không hardcode toàn thư viện.
- Ít nhất12 matured meta task origins trước development, >=12 development folds nếu chọn recipe/sampler, >=12 paired-valid locked evaluation folds. Những tasks đầu chỉ native fallback không giả là đã exercise meta đủ support.
- >=128 attempted trials/cutoff cho mỗi sampler trong study này, show attempted/completed/failed/unique riêng.
- Hai samplers tối đa theo §10.7; native và meta chia sẻ **same pool** trong một sampler. Warm-start OFF hoặc canonical arm-independent list cho selector ablation; không sử dụng riêng các arm winners cũ để làm lệch pool.
- Primary ablation: native selection vs meta selection. Một control policy có cùng architecture nhưng thông tin/history bị vô hiệu có thể thêm nếu claim information-specific, phải có budget trước outcome; không kéo cả tám arms cũ sang module acceptance mặc định.
- No sampler/model reselect bằng locked OOS; trials không được tăng sau khi outcome yếu.

Nếu chỉ làm one-path software validation, không giả nó là full scientific sampler comparison. Nếu không đủ dataset/budget, giữ software status riêng và không tự mở nhiều symbols để bù.

### 14.3. Statistic phải đặt đúng tên

\[
R_k=D_{native,k}-D_{meta,k},
\quad Q_k=SR_{FWD,meta,k}-SR_{FWD,native,k},
\]
\[
R_k=(SR_{IS,native,k}-SR_{IS,meta,k})+Q_k.
\]

- Positive R không cần đổi dấu decay; nhưng R chỉ từ lower IS không chứng minh forward retention tốt hơn.
- Guard predicted Q không thay actual OOS safeguard.
- Mean fold Sharpe không là continuous-account Sharpe.
- Same winner sau independent selection là valid zero effect.
- No-trade/zero-variance windows giữ typed status; không nhập0 làm mean đẹp.
- Khác risk/return trade-off phải báo, không post-hoc đổi mục tiêu thành risk-control superiority.
- So metadata/scores không thay evidence đúng params đã được existing run thực thi.

Nếu nghiên cứu tiếp tục dùng hurdle0.20 Sharpe reduction và OOS margin0.10 từ guide cũ, freeze vào **experiment analysis plan**, không hardcode thành runtime classifier của library. Dùng time dependence-aware inference từ raw stored outputs; không coi candidates/seeds là độc lập market samples. Confidence method phải phù hợp estimand, không lấy CI daily mean return để chứng nhận CI decay.

### 14.4. Điểm dừng của sản phẩm

Module có thể đạt `SOFTWARE_VALIDATED_OPT_IN` khi compatibility/causality/runtime/docs đạt, dù experiment là `NO_MEANINGFUL_GAIN_WITHIN_SCOPE` hoặc `LOW_PRECISION`.

Không tự promote meta thành default, không tự đổi sampler tốt nhất toàn repo. Library cho researcher công cụ đáng tin để dùng một phương pháp đã được mô tả; researcher vẫn phải kiểm hiệu quả trên task của mình.

Ngược lại, economic point gain không cho phép bỏ qua anchor mismatch, future information, malformed records hoặc hidden execution differences. Đó là yêu cầu correctness của tính năng, không tăng phạm vi thành financial-system rewrite.

<a id="s15"></a>
## 15. Definition of Done

### 15.1. Core scope

- [ ] Một module meta-selection cohesive trong QuantBT; không repo/framework phụ.
- [ ] Baseline 1.1.1 và seams thực đã đối chiếu trên host, source manifest đầy đủ.
- [ ] Sampler factory/config cũ được reuse, bốn recipes có capability/tests.
- [ ] Mode4/per_fold_causal explicit support; mode/schedule khác fail khi meta enabled, legacy off không đổi.
- [ ] Full eligible current IS pool, exact native anchor và native scores được giữ.
- [ ] Historical records có correct labels, mature availability và explicit task roles.
- [ ] Data cutoff khác completion/seal/effective time; không backdate hoặc nhập labels phát sinh khi đang compute vào snapshot cũ.
- [ ] Task/family/corpus snapshot tách đúng; sealed revisions và late labels reweight toàn origin, earlier decisions bất biến.
- [ ] Native Mode4 và final meta methodology/actual history usage được ghi riêng, shadow/fallback flags đúng.
- [ ] Ridge/basis/λ/guard/tie semantics đúng mathematical contract.
- [ ] Actual WFO hook chọn params trước current outer-OOS, không hidden raw-IS overwrite.
- [ ] Off/shadow/active có tests trên real public call path.
- [ ] Prepared Rust/Numba reuse đúng timing/capability, không thay strategy semantics.
- [ ] No per-bar meta callbacks, no dense NxN weight matrix, actual cost breakdown.
- [ ] Rust-first numeric design/dispatch qua native crate hiện có; NumPy/Numba reference/fallback có reason, capability và measurements, không mặc định NumPy-first.
- [ ] DSA/buffers/as-of indices/linear winner reduction giữ full information budget; không giảm trials/labels/features/pool để tăng tốc.
- [ ] Reference và optimized paths khớp chronological decisions/history revisions, kể cả near-boundary/resume/late-label cases.
- [ ] Host chỉ nhận existing-compatible decision/model artifact; không service/order manager mới.
- [ ] Documentation/examples/package matrix đầy đủ; no published-tag overwrite.

### 15.2. Evidence và claims

- [ ] Tất cả64 test IDs của tám phases có disposition và actual logs; subcases V1.1 về clocks/information/revisions/metadata/sequence/Rust-first đã được kiểm, không tăng phase count.
- [ ] Every run/upgrade có expected/actual/evidence và current handoff cập nhật.
- [ ] Read-only dependencies không bị sửa ngoài allowed patch list.
- [ ] Report tái sinh từ raw refs, hashes/flags được verify bằng bytes/values.
- [ ] Scientific support/trials/folds và performance sample đúng, không inflated counts.
- [ ] Không có universal-edge, global-optimal sampler, James–Stein superiority hoặc live certification claim không chứng minh.
- [ ] Owner review quyết định kết thúc hoặc request changes; không tự viết approval.

> **Kết quả mong muốn:** QuantBT có một lựa chọn mới để học từ historical candidate evaluations và chọn params ở fold tiếp theo, cùng search samplers phù hợp hơn với từng parameter space. Người dùng không bật tính năng mới vẫn nhận hành vi cũ. Phần tài chính đã có tiếp tục làm đúng vai trò của nó — không được xây lại trong module này.

<a id="s16"></a>
## 16. Sources, đọc nguồn và references

### 16.1. Internal sources đã đọc

**Ghi chú revision V1.1:** các source/publication facts và giới hạn kiểm chứng dưới đây được giữ từ V1.0, không phải một lần audit/retrieval source mới khi hợp nhất. V1.1 chỉ cập nhật năm điểm đã duyệt và Rust-first/DSA; không tuyên bố native kernels, endpoints hoặc64tests đã được triển khai/chạy. QMS-01 vẫn phải khóa exact host source trước patch.

**[I1] Source-audit archive:** `REGIME_LAB_MODE4_CAUSAL_REBUTTAL_REPAIR_5_PHASES_FINAL_VI.md`; phần VFY02–VFY05, các source ranges/hash ở §0.2. File được materialize và kiểm bytes trong phiên này:

```text
SHA256 bf983c2b63dd748d778a3d9c38360bfb6f081cb9b445d7a8044fbae63b2c7434
```

Đây là source excerpt evidence trong một archived audit, không một complete downloaded tag checkout.

**[I2] Latest meta audit:** `META_LEARNING_UPDATED_BUNDLE_OBJECTIVE_REVIEW_VI.md` ngày02/10/2026:

```text
SHA256 f89d87fa15b1c8f79e0d80ca4eead35b751b67f722e7054687c365802191ce93
```

Dùng cho lessons learned về anchor, failed labels, full-pool/panel, zero Sharpe, date compression và sampler claims. Không nói findings này tự là bugs của QuantBT1.1.1 core.

**[I3] Actual lab source excerpts:** `SOURCE_EXCERPTS_V2.md`:

```text
SHA256 b8583cbc1524ed61d39b7fc5af19d93c8e41f2f8d56b2ec955daed85487f1197
```

Đã đọc selector/search/archive runner excerpts. Đây là source của lab, **không copy nguyên vào QuantBT**.

**[I4] Consumer contract:** `CONSUMER_ENDPOINTS.md`:

```text
SHA256 5771710a55189c5c4f7a900f3ab8c06eeccfd09ffc1d8693bb681724d62c3df1
```

Giữ `data_loader`, explicit symbols, `check_val=True`, UTC semantics và release manifest. Không thêm data pipeline/collector vào module này.

### 16.2. QuantBT sources/docs

**[Q1] Publication identity, pair và attestation** — metadata kiểm ngày03/10/2026:

```text
https://pypi.org/project/quantbt-engine/
https://github.com/BobbyAxerol/quantbt/tree/v1.1.1
https://github.com/BobbyAxerol/quantbt/tree/2c811a7faaed3c274e93c60650e16207949f0a59
```

PyPI metadata đọc được; tag/hash URLs là canonical provenance targets, full checkout chưa tải được trong phiên. Không dùng HTML cache1.0.7 làm source1.1.1.

**[Q2] Optimization public documentation** — đã đọc nội dung, `main` cache không phải tag-pinned:

```text
https://github.com/BobbyAxerol/quantbt/blob/main/docs/optimization.md
```

Hỗ trợ việc tìm lại shared config/factory, warm-start/baseline-floor và ranh giới WFO. Exact API availability tại tag phải được QMS-01 xác minh.

**[Q3] Public release/readme runtime scope** — chỉ tham chiếu capability descriptions, không copy benchmark như speed guarantee:

```text
https://github.com/BobbyAxerol/quantbt
https://github.com/BobbyAxerol/quantbt/blob/main/src/quantbt/endpoint.py
https://github.com/BobbyAxerol/quantbt/blob/main/src/quantbt/walkforward.py
https://github.com/BobbyAxerol/quantbt/blob/main/src/quantbt/backends/native_wfo_public.py
```

Full contents các URLs source trên không lấy đủ trong phiên; exact source snippets được đọc từ [I1]. Đây là distinction bắt buộc giữa source-derived evidence và implementation proposal.

### 16.3. External primary technical references

**[S1] Optuna TPE — multivariate/group, startup và conditional behavior:**

```text
https://optuna.readthedocs.io/en/stable/reference/samplers/generated/optuna.samplers.TPESampler.html
```

**[S2] Optuna CMA-ES — numeric space, independent dimensions, margin/source-trial options:**

```text
https://optuna.readthedocs.io/en/stable/reference/samplers/generated/optuna.samplers.CmaEsSampler.html
```

**[S3] Optuna QMC — first trial/relative space/categorical/sequence constraints:**

```text
https://optuna.readthedocs.io/en/stable/reference/samplers/generated/optuna.samplers.QMCSampler.html
```

**[S4] Optuna FAQ — reproducibility, parallelism và sampler state:**

```text
https://optuna.readthedocs.io/en/stable/faq.html
```

**[S5] Ridge objective reference:**

```text
https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.Ridge.html
```

**[S6] PyO3 parallelism/ownership:**

```text
https://pyo3.rs/main/parallelism
```

`stable/main` docs có thể đổi sau thời điểm baseline release. Agent phải đọc docs của **version đã pin**, không nâng dependency chỉ vì website mới hơn. Những performance thresholds, API mới, module layout và phase contracts trong guide là **thiết kế đề xuất**, không phải nội dung đã được upstream hoặc bundle chứng minh tồn tại.

---

**End state của guide V1.1:** eight-phase scoped module integration, Rust-first với NumPy/Numba fallback có kiểm chứng; đúng timestamps, history revisions, final-policy metadata và parity xuyên folds. Meta-selection là một capability opt-in vào QuantBT1.1.1 baseline; không một backtest engine thứ hai, không một dự án hosting mới, không một kết luận edge được đặt trước.
