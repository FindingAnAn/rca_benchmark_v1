# Data contract và chống leakage

Grain cuối: **một dòng feature = incident_id × candidate entity_id**. Metric/log giữ grain riêng trước khi tổng hợp. Candidate inventory phải lấy từ scope/topology đã biết, không dùng nhãn root để thêm riêng đáp án đúng.

## Các file raw

| File | Trường chính | Quy tắc |
|---|---|---|
| `incidents.jsonl` | incident_id, group_id, t0, detected_at, cutoff, candidates, root_entities, is_incident | List root rỗng chỉ khi normal control; giữ root ngoài candidates để đo coverage |
| Cùng incident record | label_tier, label_source, label_available_at | Gold/Silver/synthetic khai báo rõ; nhãn train/validation phải sẵn có trước fold tiếp theo |
| Cùng incident record | domain, fault_type, release | Dùng slice report, không đưa vào feature |
| Cùng incident record | availability_mode, log_coverage_complete | Không đồng nhất không có log với log source bị mất |
| `metrics.csv` | incident_id, entity_id, metric, series_id, timestamp, available_at, value, kind | UTC epoch seconds; finite; kind gauge/rate |
| `logs.jsonl` | incident_id, entity_id, timestamp, available_at, event_id, level, template_id | Template đã normalize từ upstream; không học parser trên test |
| `changes.jsonl` | incident_id, entity_id, event_time, available_at, change_id, operation | Chỉ context đã tồn tại; không dùng outcome chưa biết |
| `topology.jsonl` | incident_id, source, target, valid_from, valid_to, available_at, relation, version | Edge source → dependent; có hiệu lực tại detected_at |

File modality chỉ bắt buộc khi bật trong config. VM connector hash cả label set và query name thành `series_id` để không gộp nhầm nhiều pod/instance. Cần tự map metric `entity_id` và ES entity về cùng cấp: ví dụ CNF hoặc service; chưa có identity dimension table/SCD trong bản base.

## DQ hiện thực

1. Checksum chặn file thay đổi, thiếu hoặc thêm vào snapshot đã seal.
2. Exact payload duplicates được loại. Cùng business key nhưng payload khác sẽ dừng run; không tự KEEP FIRST.
3. Timestamp phải có timezone nếu là chuỗi ISO. Unix numeric được hiểu là **giây**, không tự đoán milliseconds. Riêng query ES range được chuyển sang epoch_millis rõ ràng.
4. Raw counter bị từ chối; convert bằng PromQL `rate`/`increase` với window có chủ đích. Không áp `rate` lần hai lên giá trị đã là rate.
5. Metric coverage tối thiểu theo cả baseline và observation window; không fill missing bằng zero. Chưa resample grid; exporter phải dùng `step_seconds` thống nhất.
6. Log retrieval timeout/shard failure/max-pages khiến snapshot không được seal. Không giả vờ snapshot một phần là đầy đủ.
7. Split kiểm tra group không tách và cửa sổ không đè nhau; trường hợp biên không hợp lệ phải sửa kế hoạch split.

Giai đoạn base dừng khi DQ fail để người dùng sửa snapshot/version; chưa có hệ thống quarantine tự động theo từng row. File response đã thu được vẫn ở output dang dở, không có manifest hợp lệ.

## Features

| Nhóm | Feature | Công thức/ý nghĩa |
|---|---|---|
| Metric | max/mean absolute robust z | median và MAD fit trên pre-window của case; mẫu hậu detection chỉ transform |
| Metric | EWMA z | e_t = 0.3 z_t + 0.7 e_(t−1), lấy max absolute |
| Metric | missingness | 1 − min(coverage pre, post) |
| Log | error burst | log(1 + errors_post / max(1, expected_errors từ pre)) |
| Log | error rate, new template share | Theo post-window; template mới so với pre-window |
| Log | missing flag | Cờ completeness; base từ chối case incomplete khi bật log |
| Change | recency | exp(−age_seconds/3600), tuổi change tính ở cutoff |
| Topology | neighbor evidence | Max evidence ở dependent đang có trong snapshot |

Các hằng số EWMA, floor MAD và recency hiện là một phần `feature_version`; muốn tune chúng phải tạo prepared dataset mới, tránh dùng cùng tên feature version cho phép biến đổi khác nhau. `context_weight` trong statistical score có grid riêng.

## Ví dụ thao tác

Xem `examples/context/` cho field thực tế. Thay ID/time/label/topology bằng thông tin đã xác nhận. Không lấy `resolution`/`recovery_success` làm feature dự đoán sự cố trong quá khứ. Các trường đó chỉ đi vào postmortem/label store ngoài bảng feature.

`prepare` tạo `cases.jsonl`, `features.jsonl`, `splits.csv`, `dq_report.json`, config và manifest. JSONL được chọn để audit dễ; khi mở rộng có thể đổi physical storage sang Parquet mà giữ contract.
