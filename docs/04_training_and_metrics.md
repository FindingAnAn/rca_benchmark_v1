# Training hyperparameter và benchmark protocol

## Train và tune

`configs/demo.json` là experiment specification. Raw/config có dataset_version và feature_version; manifest thêm content hash, parent hash và code hash. NumPy random seed được lưu cho từng trial. Model JSON lưu scaler, weights, biases, hyperparameter và training loss, có thể nạp lại mà không chạy mã tùy ý như pickle.

| Algorithm | Train data | Search space mặc định |
|---|---|---|
| MAD | Pre-window riêng từng case, không fit label | context_weight ∈ {0, 0.3} |
| EWMA | Pre-window riêng từng case | context_weight ∈ {0, 0.3}; alpha 0.3 cố định ở feature |
| Logistic | Candidate rows của train | lr=0.02, epochs=250, L2 ∈ {0.001, 0.03} |
| PCA | Chỉ normal control windows ở train | components ∈ {2, 4}, giới hạn theo số feature |
| MLP | Candidate rows của train | hidden {16→8, 32→16}; lr {0.01,0.005}; L2 {0.001,0.01} theo 2 cấu hình |
| Deep AE | Chỉ normal control windows ở train | hidden {16→4→16,24→8→24}; lr=0.005, epochs=180 |

Mỗi algorithm có **2 cấu hình × 3 seeds = 6 trials**, toàn bộ 6 algorithm là 36 trials. Ngân sách trial ngang nhau; chi phí tính toán không ngang nhau nên báo `fit_seconds` và tổng CPU/wall time. Model supervised dùng class-balanced BCE, Adam; đây là pointwise ranking. Probability model chưa được calibrate thành xác suất nguyên nhân đúng trong production.

1. Fit scaler và weights trên train. PCA/AE dùng normal train, không lấy các entity còn lại trong sự cố làm normal giả.
2. Chấm MRR trên validation cho từng seed. Chọn cấu hình có mean MRR cao nhất; hòa chọn cấu hình xuất hiện trước trong config.
3. Với từng model đã chọn, tune threshold tối đa window F1 trên validation nếu có cả incident và normal controls; hòa chọn ngưỡng cao hơn.
4. Nạp lại model từ disk rồi đánh giá test. Không refit thêm bằng validation, không chọn seed theo test.
5. Báo mean/std qua seed, confidence interval bootstrap theo group trong từng seed, slice theo domain/fault/release.

Đây là benchmark để so sánh các family; không tự chọn một “production champion” từ test. Sau khi xem test, một experiment mới cần ghi version và dành holdout tương lai/golden set khác để tránh dùng test lặp lại làm validation ngầm.

## RCA metric

Với R là tập root thực, L là ranking và N là candidate universe:

- `Hit@k = 1` khi top-k chứa ít nhất một root; ngược lại bằng 0.
- `Recall@k = |top-k ∩ R| / |R|`. Với một root thì bằng Hit@k.
- `MRR = mean(1 / rank đầu tiên đúng)`; không thấy root thì bằng 0.
- `MAP`: trung bình average precision, chia cho số root thực, kể cả root ngoài candidates.
- `NDCG@5`: DCG dùng relevance nhị phân, chia ideal DCG của tối đa 5 root.
- `Avg@5 = mean(Recall@1, …, Recall@5)`. Khi một root, tương ứng cách tính Avg@5 của RCAEval.
- `Chance Avg@5`: kỳ vọng Avg@5 của ranking ngẫu nhiên trên đúng candidate universe, có tính root ngoài universe.
- `Lift Avg@5 = Avg@5 − Chance Avg@5`, **không phải phép chia**.

Ví dụ 8 candidates, 1 root: Chance Avg@5 = (1+2+3+4+5)/(5×8) = 0.375. Root đứng hạng 2: MRR=0.5, Hit@1=0, Hit@3=1, Avg@5=0.8. Nếu có 2 root và top-1 đúng một root thì Hit@1=1 nhưng Recall@1=0.5.

Mọi incident đã đưa vào test vẫn ở mẫu số. Inference fail trả empty ranking và điểm 0; external baseline thiếu case cũng tính 0. Báo riêng failure/coverage để không chọn model có điểm đẹp nhờ bỏ case khó.

Nguồn định nghĩa: [RCAEval evaluator](https://github.com/phamquiluan/RCAEval/blob/bb48c5aa9a24f1d5fcc716bdd479ea2d63145c90/RCAEval/benchmark/evaluation.py). Multi-root, MAP/NDCG và grouped bootstrap là phần mở rộng nội bộ.

## Detection và operational

Case score = max candidate score. AP được tính theo các nhóm score bằng nhau, tránh thứ tự của tie làm thay đổi kết quả. AP là non-interpolated PR area, không gọi là diện tích trapezoid. Precision/recall/F1 chỉ là **window-level** trên tập được chọn; positive prevalence của dataset ảnh hưởng trực tiếp precision.

Latency bao gồm dựng ma trận case + model scoring + ranking. Evidence retrieval, feature build, query và network ngoài phép đo. Không suy diễn latency đó thành time-to-diagnose đầy đủ. RAM hiện ghi `python_traced_peak_bytes`; `rss_peak_bytes` và `gpu_peak_bytes` là null.

## Ablation

Lệnh `ablate` chạy lại feature build và tune từng biến thể với cùng raw/split/seeds:

1. Metric only.
2. Log only.
3. Metric + log.
4. Metric + log + change.
5. Metric + log + change + topology.

Nguồn bị bỏ không được gián tiếp đưa vào topology score. Chưa có trace/alarm parser nên các ablation trace/alarm trong đề xuất ban đầu là phase mở rộng. Khi đo lợi ích thêm nguồn, kiểm tra paired cases và CI; không kết luận chỉ từ vài số test synthetic.

## Gate

Ngưỡng demo: Hit@3 ≥ 0.7, MRR ≥ 0.5, p95 ≤ 1000 ms và evidence coverage ≥ 0.95, không lỗi inference. Đây là tham số minh họa, chưa là SLA nội bộ. Evidence coverage chỉ xác nhận có telemetry refs, không chứng minh lời giải thích đúng hoặc causal attribution.

Synthetic luôn `DEMO_ONLY`. Dữ liệu thật chỉ được `REVIEW_REQUIRED` hoặc `RESEARCH_ONLY`; base không có cờ cho phép production. Gate vận hành còn cần baseline MDA, stability ở release mới, false alarms/hour, resource thực và SME acceptance.
