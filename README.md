# VIX 期限结构监测

每个交易日收盘后,GitHub Actions 运行 `scripts/update_vix.py` 下载 VIX9D、VIX、VIX3M、VIX6M,
计算比值和历次倒挂,写入 `docs/data/vix_term.json`;GitHub Pages 从 `docs/` 发布网页。

本地预览:
    python3 -m pip install -r requirements.txt
    python3 scripts/update_vix.py
    cd docs && python3 -m http.server 8000     # 浏览器打开 http://localhost:8000
