# Lifecycle benchmark nội bộ

Một ví dụ xuyên suốt: OCS giảm tỉ lệ xử lý thành công sau nâng cấp. CPU của nhiều pod cùng tăng. Benchmark phải kiểm tra liệu phương pháp tìm đúng entity lỗi, hay chỉ trả về pod chịu tác động mạnh nhất.

| Bước | Dùng gì | Mục đích | Input và process | Kết quả |
|---|---|---|---|---|
| 1 Survey | Catalog + SME | Chốt bài toán | Domain, fault taxonomy, nguồn có sẵn, ngân sách chẩn đoán | Dataset/algorithm/metric catalog |
| 2 Raw | VM query_range, ES PIT | Lưu bằng chứng có thể truy lại | Query theo case/window, giữ response, checksum | Raw snapshot version |
| 3 Label | Incident/ticket/playbook | Xác định đáp án tin cậy | Root entity, provenance, thời điểm nhãn sẵn có | Gold/Silver/synthetic tách rõ |
| 4 Prepare | `data.py` | Tạo input nhất quán | DQ, event/arrival time, metric/log riêng, context as-of | Candidate features + evidence |
| 5 Split | Temporal group split | Kiểm tra khả năng dùng về sau | Train → validation → test, embargo, label maturity | `splits.csv` bất biến |
| 6 Train | `models.py` | Fit baseline | Normal-only cho PCA/AE; label train cho Logistic/MLP | JSON weights + scaler + loss |
| 7 Tune | Grid và seeds | Chọn cấu hình | Cùng grid budget đã khai báo; chọn mean validation MRR | `trials.csv` + selected configs |
| 8 Evaluate | Common evaluator | So sánh công bằng | Test chỉ sau selection; cùng candidate list | Ranking, CI, slices, latency |
| 9 Register | JSON + SQLite | Truy vết | Code/config/data hashes, artifact paths | Run RUNNING/FAILED/COMPLETED |
| 10 Review | Reviewer và gate | Quyết định thử nghiệm tiếp | Xem failure cases, baseline MDA, chất lượng/latency | Research/rejected/shadow request |
| 11 Shadow | Hệ thống tích hợp tiếp | Đo vận hành thật | Dùng output score với evidence, chưa tự gọi action | Operator feedback, acceptance |
| 12 Feedback | Dataset version mới | Cải thiện có kiểm soát | Kết luận SME, drift, incident mới | Relabel/retrain/rebenchmark |

## Ranh giới quan trọng

**T0** là thời điểm sự cố được xác nhận về sau. **detected_at** là mốc hệ thống đã phát hiện và bắt đầu chẩn đoán. Feature chỉ lấy cửa sổ trước/sau `detected_at`; `cutoff = detected_at + post_seconds` là ngân sách quan sát. `t0` không dùng để suy đoán feature thời gian thực. Demo đặt detected_at bằng T0 vì đã biết thời điểm inject; do đó demo không đo detection delay.

Metric/log có `available_at <= cutoff` mới được dùng. Change và topology cũng phải thỏa điều kiện này. Các trường root, fault type, label source, recovery result, final LCM state sau cutoff không đi vào ma trận model. Rule output chưa có SME xác nhận là Silver, không coi là Gold chỉ vì rule chạy thành công.

Historical `query_range` chỉ trả thời điểm sample, không chứng minh thời điểm sample tới hệ thống. Connector bắt buộc đánh dấu `availability_mode=retrospective`. Muốn kiểm tra strict online replay cần export arrival time từ hệ thống ingestion sang canonical raw, rồi đặt `recorded`.

## Vai trò trong nhóm

| Chủ sở hữu | Trách nhiệm và đầu ra |
|---|---|
| Data owner | Query, entity mapping, time/units, completeness, retention |
| NOC/SME | Root label, confidence, evidence và nhận xét ranking |
| Data Scientist | Feature, split, model, hyperparameters, error analysis |
| MLOps/Platform | Environment, job, artifact store, registry, resource measurement |
| Product/service owner | Chốt SLA, phạm vi shadow, acceptance và quy trình promotion |

Base ghi nhận review nhưng không coi một lệnh CLI là hệ thống phân quyền production. Promote/canary/rollback cần tích hợp với IAM và workflow nội bộ.

## Mapping PL03

- `mda-rca-engine`: baseline root alarm từ Drools; chuyển sang entity qua inventory mapping.
- `mda-da`: baseline anomaly timeseries. Cần đánh giá detection riêng trước khi so với RCA.
- `lib-enrichment`: nguồn identity/topology phục vụ tạo candidate.
- `vCNFM/vNFVO`: LCM context, phân biệt MANO heal và Kubernetes tự heal.
- `vLogger/Elasticsearch`: connector log mới cho benchmark; không mặc định MDA hiện tại đã đọc ES trực tiếp.
- `vDecision`: điểm tích hợp action ở phase sau, không được gọi từ benchmark.
