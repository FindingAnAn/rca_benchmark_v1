# Hướng dẫn vận hành

## 1 Chuẩn bị môi trường

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m unittest discover -s tests -v
```

Chạy từ project root. Các dependencies của RCAEval upstream phải ở môi trường riêng nếu muốn reproduce official methods; không cài toàn bộ research stack vào môi trường ingestion. `pip install -e ".[rcaeval]"` chỉ thêm pandas/pyarrow cho importer Parquet, không cài package RCAEval.

## 2 Thử demo

```powershell
python -m rca_bench demo --config configs/demo.json --output runs/demo_new
python -m rca_bench registry --db runs/demo_new/registry.sqlite
```

Mở `runs/demo_new/run/report.html`. `trials.csv` có mọi cấu hình đã thử. `models/` có weights/scaler. `predictions/` có ranking và bằng chứng từng case theo seed. Không thay đổi thư mục raw/prepared đã seal.

## 3 Thu thập dữ liệu nội bộ

1. Copy `examples/context` thành thư mục context mới và điền incident/control thật. Phải có đủ group theo thời gian, nhãn Gold và candidates đúng inventory.
2. Copy `configs/sources.example.json` rồi sửa URL, tenant, metric PromQL, ES index/field/filter. `entity_id` trong ví dụ là contract đích, không phải khẳng định exporter thật đã có label đó.
3. Dùng quyền read telemetry và mở/đóng ES point-in-time. Authorization đầy đủ lấy từ biến môi trường, ví dụ `Bearer …` cho VM và `ApiKey …` cho ES; không ghi secret vào config.
4. Historical VM export đặt `availability_mode=retrospective`. Với strict online replay, nhập canonical raw có arrival time từ hệ thống thu thập.

```powershell
# Điền secret qua hệ thống quản lý secret hoặc environment của phiên làm việc.
python -m rca_bench ingest --sources configs/sources.internal.json --context data/internal/context_v1 --output data/internal/raw_v1
```

VM dùng query range có chunk, step, timeout; ES dùng PIT/search_after và đóng PIT khi xong hoặc lỗi. Output giữ response nguyên bản, query specification và checksum. Hãy áp chính sách lưu trữ nội bộ cho raw log vì response có thể chứa thông tin nhạy cảm.

Nếu đã có export canonical, dùng `seal-raw` một lần:

```powershell
python -m rca_bench seal-raw --raw data/internal/raw_v1 --dataset-version internal-gold-0.1.0
```

Raw lỗi sẽ dừng DQ; sửa vào raw version mới. Không sửa manifest để ép vượt gate.

## 4 Prepare và benchmark

Copy demo config thành `configs/internal.json`: sửa `dataset_version`, `label_tiers=["gold"]`, modality, pre/post/step và gate đã thống nhất. `n_cases` chỉ điều khiển generator demo. `cutoff` của từng case phải bằng detected_at + post_seconds.

```powershell
python -m rca_bench prepare --raw data/internal/raw_v1 --config configs/internal.json --output data/internal/prepared_v1
python -m rca_bench benchmark --prepared data/internal/prepared_v1 --config configs/internal.json --output runs/internal_001
```

Public RCAEval thường không có normal controls. Khi chưa bổ sung normal windows, chỉ bật Statistical và supervised Logistic/MLP phù hợp; PCA/AE cần normal train nên sẽ dừng thay vì tự giả định mọi non-root là normal. Benchmark detection sẽ không có threshold nếu validation chỉ toàn incident.

## 5 Import dữ liệu RCAEval

```powershell
python -m rca_bench import-rcaeval --catalog examples/rcaeval_catalog.example.json --output data/rcaeval_raw_v1
```

Đây là mẫu cấu hình; sửa đường dẫn tới `metrics.csv`/`metrics.parquet` đã tải. Dùng mapping column→entity tường minh để xử lý service có dấu gạch dưới. Với `metrics.json` raw, dùng `RCAEval.utility.read_metrics(case_dir)` trong môi trường upstream rồi xuất wide CSV. Dữ liệu imported có content hash và upstream_ref.

Catalog phải lấy nhãn thật từ dataset index/ground truth; không suy ra đáp án từ kết quả BARO. Chỉ import metric trong base. Group repetition và chọn window/baseline theo dữ liệu thực; nếu case ngắn hơn pre=60 phút thì tạo config khác và ghi feature version.

Muốn reproduce paper, chạy CLI upstream với pinned commit ở môi trường riêng. Kết quả public import theo protocol nội bộ không được đặt cạnh bảng paper như cùng một phép đo.

## 6 So với rule MDA

Xuất `incident_id`, `observation_cutoff`, `ranks`, `evidence`, `rule_version` như `examples/mda_predictions.example.jsonl`. Chuyển root alarm thành entity cùng grain. Chỉ đưa test cases; cutoff phải trùng.

```powershell
python -m rca_bench benchmark --prepared data/internal/prepared_v1 --config configs/internal.json --external-predictions data/internal/mda_test.jsonl --output runs/internal_002
```

Không lấy output rule làm cả label Gold lẫn baseline so sánh nếu chưa có xác nhận độc lập.

## 7 Ablation và review

```powershell
python -m rca_bench ablate --raw runs/demo_new/raw --config configs/demo.json --output runs/ablation_new
python -m rca_bench review --db runs/registry.sqlite --run-id internal_002 --decision shadow_requested --reviewer "TEN_NGUOI_DUYET" --reason "Ghi ket qua xem xet va pham vi shadow"
```

`review` chỉ lưu yêu cầu/xét duyệt vào audit table, không triển khai hoặc gọi vDecision. Với run demo, DB nằm ở thư mục output demo; với `benchmark` độc lập, DB nằm ở thư mục cha của run.

## 8 Scoring và drift

```powershell
python -m rca_bench score --model runs/internal_001/models/ml_logistic-c0-s42.json --features data/internal/current_features.jsonl --output data/internal/current_ranking.jsonl
python -m rca_bench drift --reference data/internal/reference_features.jsonl --current data/internal/current_features.jsonl --output data/internal/drift.json
```

Chọn đúng model path được ghi trong `summary.json`, không mặc định `c0` luôn thắng. Lệnh `score` chỉ cần incident_id, entity_id, features và evidence, không cần root label. Drift dùng PSI với bins học từ reference và smoothing; so cùng population/cửa sổ/feature version. Mốc 0.2 chỉ tạo cờ review, không tự train hay promote.

Feedback SME dùng `examples/feedback.example.jsonl`: kết luận, reviewer, evidence và thời điểm nhãn sẵn có. Đưa kết quả đã duyệt vào **dataset version mới**, tạo lại split và benchmark. Chưa có web app chỉnh nhãn.

## 9 Khi mở rộng

Ưu tiên 10–20 incident Gold để kiểm tra identity/time/labels trước khi tăng số thuật toán. Sau đó thêm Parquet/object storage, MLflow, orchestrator và CI/CD theo nhu cầu thật. Các phần chưa có: resume ingestion/checkpoint, incremental features, scheduler, RBAC registry, online event matching, full native/GPU resource measurement, deploy/canary/rollback, trace/alarm processing, và SCD identity mapping.
