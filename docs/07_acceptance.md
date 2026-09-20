# Phạm vi bàn giao và kết quả kiểm chứng

## Đã hoàn thành

| Hạng mục | Bằng chứng |
|---|---|
| Đối chiếu nguồn | Ba DOCX, notebook viễn thông, structure_mau và RCAEval pinned commit; hashes trong `catalog/source_manifest.json` |
| Survey dataset/algorithm/metric | Markdown dễ đọc và 3 catalog CSV có trạng thái implemented/survey |
| Raw connector | VictoriaMetrics query_range có chunk; ES PIT/search_after có timeout/partial-response checks |
| Dataset lifecycle | Raw/prepared snapshot, checksum, version, DQ, temporal/group split, label maturity |
| Training | 6 baseline thực thi, scaler/weights/loss/seed/config lưu lại, nạp model để test |
| Hyperparameter | 36 trial cho mỗi experiment đầy đủ; validation-only selection |
| Benchmark | Ranking multi-root, chance floor/lift, slice, grouped CI, sampled-window detection, resource scope rõ |
| Product baseline | Nhập ranking MDA/Drools theo cùng candidate grain và cutoff, case thiếu vẫn ở mẫu số |
| Ablation | 5 modality settings × 6 algorithm = 30 dòng so sánh, mỗi setting tune lại trên validation |
| Quản lý nội bộ | SQLite run registry + review audit; model cards và lineage files |
| Theo dõi | PSI drift report và mẫu feedback để tạo dataset version mới |
| Sử dụng | CLI, PowerShell launcher, README/runbook và notebook walkthrough |

## Đã kiểm thử

`reports/validation.json` ghi kết quả thực thi; `reports/test_results.txt` chứa test log.

- **19 tests đạt**, gồm leakage thời gian/nhãn, group split/label delay, conflicting duplicates, checksum, model training/save/load/determinism, ranking multi-root/ties, VM chunk boundaries, ES pagination/PIT cleanup, public importer, external report và failed run status.
- **7 snapshots** được verify lại toàn bộ file hashes.
- **6 runs** ở trạng thái COMPLETED, artifacts và code hashes khớp bản code bàn giao.
- **Notebook** được thực thi tuần tự toàn bộ code cells.
- **30 dòng ablation** được tạo từ 5 settings với cùng tập raw.

Đây là kiểm thử local và connector bằng response giả lập. Không đánh đồng với kiểm thử live trên hạ tầng thật. Báo cáo HTML được tạo và kiểm tra dữ liệu/link cấu trúc; chưa có xác nhận UI bằng ảnh chụp trình duyệt.

## Nhận xét về demo

Dataset synthetic có 90 windows: 54 train, 18 validation, 18 test. Test có 15 incident và 3 normal controls. Các phương pháp dùng 8 candidates/case. Full-modality demo cho MRR 1.0 ở một số baseline và khoảng 0.944 ở deep AE; điều này phản ánh fixture dễ phân biệt, không phải chứng minh Statistical/ML/DL nào tốt nhất.

Ở ablation metric-only, MAD có MRR khoảng 0.767; thêm log đưa lên 1.0 trên fixture này. Đây chỉ cho thấy nhánh log được nối và có ảnh hưởng tới ranking. Dataset generator dùng log error pattern rõ nên chưa đủ đo lợi ích thực của đa nguồn, topology hoặc change.

Base hiện **không tái lập benchmark chính thức của RCAEval**, không chạy các method upstream, không huấn luyện trên 735 case thật. Đã đối chiếu mã nguồn và triển khai importer/protocol nội bộ; public data cần tải và cung cấp mapping/label catalog đúng trước khi benchmark.

## Những phần chưa có dữ liệu để nghiệm thu

| Cần bổ sung | Vì sao |
|---|---|
| URL/tenant/query thật của VM; ES index/field và quyền read/PIT | Kiểm tra schema, performance và độ đầy đủ của telemetry |
| Mapping service/CNF/VDU/pod/node theo thời gian | Candidate identity giữa các nguồn phải thống nhất |
| Incident Gold và normal periods | Fit/tune/test có ý nghĩa và đo false alerts |
| Rule output MDA + rule version | So model mới với baseline đang dùng |
| Topology/LCM snapshots có available_at | Tránh dùng trạng thái hiện tại để giải thích lịch sử |
| Continuous replay và operational feedback | Đo event metrics, delay, MTTI/MTTR, acceptance |

Không có endpoint action, deploy/canary/rollback, RBAC production, automatic remediation hay automatic promotion. Đây là phạm vi bản base; phase tiếp theo ưu tiên nối 10–20 incident đã xác nhận để kiểm tra contract, rồi mở rộng holdout cho benchmark đủ tin cậy.

## Tiêu chí chuyển sang thử shadow

Data owner xác nhận completeness/identity/time; SME duyệt nhãn; DS khóa split/config và phân tích case sai; service owner chốt gate latency/false-alert/cost. Sau đó mới gửi output top-k + evidence sang hệ thống hỗ trợ vận hành. Các ngưỡng demo phải thay bằng tiêu chí thực tế; review record trong SQLite là audit local, không thay cho phê duyệt vận hành.
