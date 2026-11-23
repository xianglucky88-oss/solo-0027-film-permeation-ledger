# 薄膜透过质量账：数据规格

## 使用者和目标

工业薄膜试验数据员提交合成受液池体积和膜面积、采样及补液计划、空白读数、浓度阈值和测量时间，得到空白校正累积透过量、缺测/低限区间、平稳通量窗口与试片对账。服务在回环地址启动，仅供本机处理。无需登录，不控制真实设备或放行生产数据。

## 数据合同

样品浓度和空白为微克／毫升，质量为微克，时刻为分钟。假设池液混匀、补液不增加被测溶质。累积质量为取样前池中质量加过往取走的质量，再除以膜面积。报告限保留上下界；取走缺失浓度的液体后，后续质量不再确定，体积仍可确定。通量区间是相邻质量区间的保守差值，不宣称独立精确误差。 相邻两次取样共有的更早抽取量可抵消；先扣除早一笔取样移走的体积，再用各自的净浓度界限求单位面积单位时间的增量。

`examples/sample.json` 是字段及合法取值示例。`alternate.json` 是同一对象的另一有效输入，`reject.json` 是应被阻止的输入。对象在输入顶层以 `id` 标识；归约行使用原始身份或来源组件组合作为标识。缺测映射为 `null` 或待定状态，不当成数值零。接口接受不超过 512 KiB 的 UTF-8 JSON 对象；重复字段、非法数值或域内冲突返回 400。

成果保存数据合同版本、原始包、各阶段输出、输入摘要和整包摘要。SQLite 通过唯一摘要让同一个有效产物只存一次，错误输入不落库；版本比对只允许同一对象和同一合同版本。校验摘要用于本地内容完整性，不是签名。

## 生产工作流

| 工作流 | 公开入口 | 主要样例观测 |
|---|---|---|
| 受液核量 | `POST /permeance/api/evaluate 的 outputs.liquid` | 取样二 的 处理后 为 9 |
| 空白校正 | `POST /permeance/api/evaluate 的 outputs.blank` | 取样一 的 来源证据 为 ["零点", "空白二"] |
| 浓度区间 | `POST /permeance/api/evaluate 的 outputs.bounds` | 取样二 的 上界 为 2 |
| 透过质量 | `POST /permeance/api/evaluate 的 outputs.mass` | 取样三 的 下界 为 19 |
| 区段通量 | `POST /permeance/api/evaluate 的 outputs.flux` | 取样一/取样二 的 下界 为 -0.4 |
| 阈值穿越 | `POST /permeance/api/evaluate 的 outputs.crossing` | 取样二 的 状态 为 "possible" |
| 队列复测 | `POST /permeance/api/evaluate 的 outputs.revisit` | 取样五 的 状态 为 "unresolved" |
| 区段净增量 | `POST /permeance/api/evaluate 的 outputs.increment` | 取样四/取样五 的 状态 为 "blind" |
| 平行版本差分 | `POST /permeance/api/compare` | 异版产生差异，同版无差异，跨对象拒绝 |
| 封存版本 | `POST /permeance/api/seal` | 同输入仅写入一次，旧版不随对照改变 |
| 导出交接 | `GET /permeance/api/export/<摘要>` | 下载头有效且内容完整保留历史快照 |

## 职责

- `permeance/contract.py`：JSON 与领域字段边界。
- `permeance/domain.py`：解析领域单位与归约事实。
- `permeance/rules.py`：消费归约证据和约束，产生业务判定。
- `permeance/artifacts.py`：成果规范编码、摘要与差分。
- `permeance/archive.py`：SQLite 历史版本与原子封存。
- `permeance/service.py`：串联归约、比对和历史读取。
- `permeance/server.py`：本机 HTTP 及静态界面入口。
- `web/ui.js`：归约阶段、图形、归档与交互。
- `permeance/reconcile.py`：联合原始归约事实与业务判定，推导区段净增量。

浏览器显示来源和判定结果；发布决定由服务端归约。自动化测试套件留置。每条工作流的有界核对命令见 `.project-runtime.json`。

## 扩展复核

顶层可选 `review`；省略时基础包与旧版逐字段一致。启用时增加下列结果，与原数据共同封存，旧版与增强版可按阶段比对。`examples/review-sample.json` 给出有效输入结构。

- `windows` 任意取样窗净增量：消去两个端点共有的早先抽样量，保留窗内非零项及符号界限。
- `agreement` 相邻通量口径对照：区分同值、缩窄区间和抵消旧盲区后可量化。
- `draws` 抽样下游影响：只有非零抽样才传播至随后累积质量。
- `blank_footprint` 空白复用范围：反查每个空白点进入哪些数据，并分开空白与浓度状态。
- `threshold_review` 阈值观察范围：分开最早未排除和首次有证据越限，不推定真实越限时刻。
- `checkpoints` 独立池量复核：独立池量与取样后池量核对，不回填浓度或预测池量。
- `zero_draw_gaps` 缺测传播分类：缺测若没有取液只影响本次快照，有取液才传给以后。
- `steady_state` 稳态通量与滞后复核：在同一恒定暴露条件下，用既有单位面积累计量证据区间复核稳态模型 `M = J·(t−L)`，J 为正斜率、L 为滞后且不晚于稳态起点。

稳态复核只消费 `outputs.mass` 的 `[lo, hi]` 证据区间，不把区间改成中点，不改写原累计量与过限判断。资料管理员在 `review.steady_state` 中于计算前指定：允许的起点取样集合、斜率范围 `slope`、滞后范围 `lag`、最少拟合点数 `min_fit_points`、拟合最小时长 `min_fit_span`，并对每个起点显式列出拟合点 `fit` 与后续独立复核点 `holdout`（均按取样时刻严格递增，复核点晚于全部拟合点）。

对每个允许起点保留全部指定拟合点：任一拟合或复核点缺证（`lo/hi` 为 `null`）不得悄悄删除，该起点判为 `evidence_incomplete` 并在记录中保留缺证点。全部约束在 `(J, b)`（`b = −J·L`）平面都是线性半平面，可行解释是凸多边形，用半平面裁剪求精确可行域；只有同一组 `(J, L)` 同时落入所有拟合点证据区间才算可行。留出点用这同一组参数继续裁剪，不为每个复核点重选参数。

汇总逐起点报告 `feasible`（留出后仍可行，含拟合可行域与留出后幸存域的 J、L 范围及所据拟合/留出记录）、`no_solution`（确证无解，区分拟合即无解与留出后无解）、`evidence_incomplete`（证据不全）。多个可行起点的斜率与滞后窗重叠时给 `coexistent` 及共同参数范围；皆可行却互不相容时给 `incompatible_lags`，分别报告、不拼成确定参数；无可行起点给 `confirmed_no_solution`。`examples/steady-film-a.json` 至 `steady-film-d.json` 分别覆盖多起点共存、单起点可行、各留出点单独可解释而联合无解、缺证；`steady-reject.json` 是应被阻止的非法方案。
