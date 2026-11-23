# 薄膜透过质量账

工业薄膜试验数据员使用浏览器处理合成受液池体积和膜面积、采样及补液计划、空白读数、浓度阈值和测量时间，交付空白校正累积透过量、缺测/低限区间、平稳通量窗口与试片对账。全部内置数据为合成样例，不连接生产设备或在线服务。

## 本机运行

Python 3.11 或以上（含标准库 SQLite），不需要下载包。现代浏览器负责界面；Node.js 仅用于构建时检查 JavaScript 语法。

```sh
python3 -m permeance.server
```

访问 `http://127.0.0.1:8864`。默认把封存成果写入 `.local/permeance.sqlite`；可传 `--port`、`--db` 覆盖。界面先显示合成首例；可切换对照、导入 JSON、查看证据明细、封存成果、比较同对象版本或下载指定版本。

## 手动核对

```sh
python3 -m permeance.check_flow liquid
python3 -m permeance.check_flow increment
python3 -m permeance.check_flow export
```

这些命令在临时成果库和临时回环端口运行实际 HTTP 接口，分别核对样例、对照和拒绝路径。`examples` 保存业务示例及可人工核算的观测点。完整命令见 `.project-runtime.json`；自动化测试套件留置，不包含私有验收测试、缺陷任务或参考解答。

### 扩展复核

使用「复核样例」，随后在「扩展复核」切换各项结果。有效输入见 `examples/review-sample.json` 与 `examples/review-alternate.json`。例如运行 `python3 -m permeance.check_flow windows` 可核对派生结果、拒绝非法复核和基础版本兼容性。

### 多档测量

取样点可附 `tiers` 多档测量（独立编号、稀释倍数、状态、读数或限值），每档还原到未稀释试液后求交，交集只做一次空白校正；档间冲突保留为 `conflict`，只剩单侧界记 `open`，不补零或仪器满量程。样例见 `examples/tiers.json`，运行 `python3 -m permeance.check_flow tiers` 核对两档互补成界、正抽冲突传播后续累计、零抽冲突不污染后账及旧记录口径不变。
