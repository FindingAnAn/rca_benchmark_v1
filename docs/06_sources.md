# Nguồn đã đối chiếu

## Tài liệu tại workspace

| Nguồn | Nội dung đã sử dụng | Ánh xạ triển khai |
|---|---|---|
| `RCA/02_De_xuat_Benchmark_RCA_Stat_ML_DL_Lifecycle_v2_PL03.docx` | Survey, 3 tracks, time/incident split, ablation, lifecycle và outputs | Data contract, runner, metrics, registry, docs |
| `RCA/01_Cot_loi_5G_NFV_MANO_AN_Fault_Change_v2_PL03.docx` | Core/MANO/OCS, topology/lifecycle, phân biệt fault/alarm/action | Entity ranking, change context, review và shadow boundary |
| `RCA/PL03.0_20260202_Thiet ke chi tiet phan he MANO he thong vOCS4.0.docx` | `mda-rca-engine`, `mda-da`, vmselect, vLogger/ES, vCNFM LCM, lib-enrichment | Product baseline adapter, connectors, as-of context |
| `Telecom_Abnormal_Detection_MLOps_Reference_Architecture.ipynb` | Metric/log riêng, Bronze/Silver/Gold, DQ và leakage controls | Raw→prepared→model pipeline; evidence fusion ở incident |
| `structure_mau.txt` | MLOps project layout | Tách module thực thi, configs, tests, docs, experiments |

Đã trích nội dung đoạn văn và bảng của ba DOCX để đối chiếu nghiệp vụ. Đây là kiểm tra nội dung, không phải QA layout/render của các DOCX gốc. Tài liệu gốc được giữ nguyên. Bản triển khai không xác nhận rằng mô tả PL03 chính là trạng thái hệ thống đang vận hành hôm nay.

## Nguồn công khai

| Nguồn chính | Nội dung dùng |
|---|---|
| [RCAEval pinned source](https://github.com/phamquiluan/RCAEval/tree/bb48c5aa9a24f1d5fcc716bdd479ea2d63145c90) | Dataset layout, e2e rank interface, evaluation protocol |
| [RCAEval evaluator](https://github.com/phamquiluan/RCAEval/blob/bb48c5aa9a24f1d5fcc716bdd479ea2d63145c90/RCAEval/benchmark/evaluation.py) | Avg@5, chance floor, lift dạng hiệu |
| [RCAEval data reader](https://github.com/phamquiluan/RCAEval/blob/bb48c5aa9a24f1d5fcc716bdd479ea2d63145c90/RCAEval/utility/__init__.py) | Wide DataFrame time, CSV/Parquet compatibility |
| [VictoriaMetrics API examples](https://docs.victoriametrics.com/victoriametrics/url-examples/) | query_range, tenant path, query/start/end/step |
| [Elasticsearch pagination](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/paginate-search-results) | PIT, search_after, sort token và latest PIT id |
| [AIOps Challenge 2020](https://github.com/NetManAIOps/AIOps-Challenge-2020-Data) | Survey modalities/labels và điều kiện nguồn |
| [LogHub](https://github.com/logpai/loghub) | Survey log anomaly datasets |

Commit upstream ngày 06/09/2026; bản đối chiếu được tải và hash trong phiên triển khai này. `catalog/source_manifest.json` ghi SHA-256 của tài liệu local và file code đã đọc. Hash giúp nhận ra drift; không thay thế việc kiểm chứng lại nội dung khi đổi phiên bản.

Base tự viết module, không copy implementation của các research methods. License của từng baseline trong RCAEval có thể khác nhau; survey không có nghĩa mọi implementation đều sẵn sàng dùng lại. Muốn vendor method nào thì đối chiếu license của chính method đó tại commit được pin.
