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

### 整卷批次判定

使用「整卷批次」按开试前登记的分区和样片清单做批次审结。登记须给出共用的单位面积透过限值、从各片试验起点计算的必测时点、判断截止时点和每区最少合格片数。逐片以累积质量区间为证：截止前任一样点下界到限即未通过；截止内每个必测点有证且所有可用样点（含额外实测点）上界严格低于限值才合格；缺片、缺点、无可信区间或区间跨限一律计入未定并指明阻断来源。每区分别报最少与最多可能合格片数，任一区上界不达标整卷拒收，所有区下界达标才放行，否则待补证。

```sh
python3 -m permeance.check_flow roll
```

该检查同时核对两种交接情形：两卷总合格片数相同但只有一卷每区都够；某片末次有证且低于限值，却因中间缺测或曾经有证到限而不能计作合格。有效登记见 `examples/roll-sample.json` 与 `examples/roll-alternate.json`，非法登记见 `examples/roll-reject.json`。
