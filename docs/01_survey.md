# Survey dữ liệu thuật toán và metric

Khảo sát ngày 21/09/2026, đối chiếu code RCAEval ở commit ghi trong README. Ba quyết định cho bản base: lấy incident làm đơn vị dữ liệu; chấm ranking entity thay vì accuracy từng dòng; quản lý phiên bản dữ liệu và model cùng nhau.

## Dataset

| Bộ dữ liệu | Dữ liệu và nhãn | Dùng trong nội bộ | Trạng thái ở bản base |
|---|---|---|---|
| RCAEval RE1 | Metric, root service/indicator | Kiểm thử public metric RCA | Import CSV/Parquet với mapping tường minh |
| RCAEval RE2 | Metric/log; trace tùy hệ thống | Thử đa nguồn | Chưa tự import raw log/trace |
| RCAEval RE3 | Fault ở mức code, đa nguồn | Case khó và transfer | Survey, có thể đưa metric vào cùng importer |
| AIOps Challenge 2020 | Business/platform metrics, traces, fault time/type/location | Nghiên cứu localization | Survey; điều kiện nguồn giới hạn mục đích sử dụng |
| LogHub HDFS/BGL | Log và nhãn bất thường tùy bộ | Parser/anomaly detection | Không thay thế ground truth RCA |
| Nội bộ MANO/Core/OCS | VM + ES + topology + LCM + kết luận SME | Quyết định triển khai | Contract/connector sẵn, cần dữ liệu Gold |
| Synthetic demo | 90 case, 8 entity, metric/log/change/topology | Kiểm tra tích hợp và leakage | Đã chạy, không đo chất lượng production |

RCAEval mô tả 735 failure cases trong RE1/RE2/RE3. TORAI là phiên bản xử lý của RE2, không cộng thêm như các sự cố độc lập. Dataset công khai thiếu control windows bình thường nên không tự suy ra precision/false alarm rate. Hãy giữ `system + fault + target + experiment campaign` trong `group_id` để các repetition liên quan cùng fold; nếu group trải qua biên thời gian, bản base sẽ từ chối split thay vì random hóa.

Nguồn: [RCAEval](https://github.com/phamquiluan/RCAEval), [AIOps 2020](https://github.com/NetManAIOps/AIOps-Challenge-2020-Data), [LogHub](https://github.com/logpai/loghub).

## Thuật toán

| Nhóm | Đã thực thi | Nên mở rộng khi nào |
|---|---|---|
| Sản phẩm hiện hành | Adapter nhận ranking MDA/Drools | Khi export được root alarm → entity và cutoff của rule |
| Statistical | MAD, EWMA + fusion đơn giản | Thêm STL khi có seasonality, CUSUM/change-point khi cần xác định thời điểm |
| ML supervised | Logistic candidate ranker | Thêm RF/XGBoost khi có đủ Gold labels và nonlinear feature interactions |
| ML unsupervised | PCA reconstruction | Thêm Isolation Forest/LOF, so với symptom propagation và missingness |
| DL tabular | MLP 2 hidden layers; deep AE | Chỉ tăng độ phức tạp khi validation gain ổn định |
| DL sequence/graph | Chưa triển khai | LSTM/TCN khi có chuỗi dài; GNN khi topology được version và có đủ case |
| Causal RCA | Chưa triển khai | CIRCA/RCD/CausalRCA cần giả định graph, CI test, runtime/license riêng |

Không gọi `stat_mad` là BARO: bản này dùng MAD, độ lệch tuyệt đối hai phía, fusion và DQ riêng; implementation BARO upstream dùng RobustScaler và xếp hạng theo độ lệch lớn nhất. Không gộp causal inference vào DL chỉ vì một method có neural component. Cần survey theo **supervision, input, assumption và output**, bên cạnh nhóm Statistical/ML/DL.

Nguồn code: [BARO upstream](https://github.com/phamquiluan/RCAEval/blob/bb48c5aa9a24f1d5fcc716bdd479ea2d63145c90/RCAEval/e2e/baro.py). Không vendor hoặc thực thi các method upstream có dependency riêng trong môi trường base.

## Metric và thuật toán phải ghép đúng nhiệm vụ

| Nhiệm vụ | Metric | Base hỗ trợ |
|---|---|---|
| Root entity ranking | Hit@1/3/5, Recall@1/3/5, MRR, MAP, NDCG@5, Avg@5 | Có, gồm multi-root và root ngoài candidate set |
| Đối chiếu ngẫu nhiên | Chance Avg@5, Lift Avg@5 | Có, cùng candidate universe |
| Detection trên sampled windows | Precision, Recall, F1, AP | Có khi validation có normal controls |
| Continuous detection | Event matching, delay, false alarms/hour | Chưa; cần replay liên tục và cách gộp alarm |
| Fine-grained indicator/cause type | Indicator Hit@k, cause Macro-F1 | Chưa; nhãn hiện tại chỉ root entity |
| Operational | p50/p95/p99 scoring, CPU time, wall time | Có, chưa gồm query/feature build/network |
| Resource | Python traced memory | Có; không đại diện RSS/GPU peak |
| NOC outcome | Human acceptance, MTTI/MTTR, rollback precision | Chưa; cần feedback/action outcome thực |

Danh mục dạng máy đọc được nằm trong `catalog/`. Không dùng một weighted score để che trade-off chất lượng và chi phí.
