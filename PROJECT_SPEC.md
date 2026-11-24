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
| 整卷批次判定 | `POST /permeance/api/adjudicate 的 outputs.roll/zones/pieces` | 右区 状态 为 "pending"；右区-乙片 阻断原因为 "crossing_interval" |
| 封存版本 | `POST /permeance/api/seal` | 同输入仅写入一次，旧版不随对照改变 |
| 导出交接 | `GET /permeance/api/export/<摘要>` | 下载头有效且内容完整保留历史快照 |

## 职责

- `permeance/contract.py`：JSON 与领域字段边界。
- `permeance/domain.py`：解析领域单位与归约事实。
- `permeance/rules.py`：消费归约证据和约束，产生业务判定。
- `permeance/roll.py`：开试前登记的分区与样片清单校验，逐片与整卷批次判定。
- `permeance/artifacts.py`：成果规范编码、摘要与差分。
- `permeance/archive.py`：SQLite 历史版本与原子封存。
- `permeance/service.py`：串联归约、比对和历史读取。
- `permeance/server.py`：本机 HTTP 及静态界面入口。
- `web/ui.js`：归约阶段、图形、归档与交互。
- `permeance/reconcile.py`：联合原始归约事实与业务判定，推导区段净增量。

浏览器显示来源和判定结果；发布决定由服务端归约。自动化测试套件留置。每条工作流的有界核对命令见 `.project-runtime.json`。

## 整卷批次判定

一卷薄膜按开试前登记分左、中、右等分区，每区登记样片清单。一卷的合格均值不能用另一区的合格片顶掉某区的失败片，因此判定以**分区**为单位，整卷结论只由各区的最少与最多可能合格片数推出。

登记在开试前固定，顶层 `POST /permeance/api/adjudicate` 接收并校验：全卷共用的单位面积透过限值 `limit`、判断截止时点 `cutoff`、从各片自己的试验起点计算的必测时点 `required_points`（均不晚于截止）、每区最少合格片数 `min_pass`，以及 `zones` 内每片一次登记试验。同一片只允许开试前登记的那次试验，输入里的试验不得自带 `id` 或限值（限值以整卷登记为准），也不接受后来表现更好的替换试验。登记里声明的 `extra_points` 额外实测点同样参与审结。

判定只消费现有校正并计入抽液后的**累积质量区间**（复用 `domain` 与 `rules` 归约），不在两次取样之间插值，也不把截止以后才取得的样点倒填：

- **确认未通过（fail）**：截止时点及以前的任一实际样点，其可信区间下界达到限值（`lo >= limit`）。末次有证且低于限值，不能抹掉早先一次有证到限。
- **确认合格（pass）**：截止以内每个必测点都有对应取样且有可信区间，并且这段期间所有可用样点（含落在截止前的额外实测点）的上界都严格低于限值。额外点已登记但无对应取样或无可信区间，同样不能报通过。
- **未定（undetermined）**：缺片、必测点缺证、截止前样点无可信区间（含早先抽液带走未知质量造成的下游盲区）、或区间跨限（上界到限而下界未到限）。每条阻断都指明是哪片、哪次取样（`sample`）、哪个相对时点（`offset`）或哪笔早先抽液（`evidence`）。

`outputs` 给三层结果：`roll`（整卷）、`zones`（每区登记数、已证合格/未通过/未定数，以及最少可能 `min_possible` 与最多可能 `max_possible` 合格片数）、`pieces`（逐片结论与阻断明细）。任何一区连上界都不达标（`max_possible < min_pass`）则整卷 `reject`；所有区下界均达标（`min_possible >= min_pass`）才 `release`；其余情形 `pending` 待补证。`examples/roll-sample.json`、`roll-alternate.json` 给出两种交接情形（总合格片数相同但只有一卷每区都够；末次合格却因中间缺测或曾经到限不能计合格），`roll-reject.json` 是应被 400 阻止的非法登记。

## 扩展复核

顶层可选 `review`；省略时基础包与旧版逐字段一致。启用时增加下列结果，与原数据共同封存，旧版与增强版可按阶段比对。`examples/review-sample.json` 给出有效输入结构。

- `windows` 任意取样窗净增量：消去两个端点共有的早先抽样量，保留窗内非零项及符号界限。
- `agreement` 相邻通量口径对照：区分同值、缩窄区间和抵消旧盲区后可量化。
- `draws` 抽样下游影响：只有非零抽样才传播至随后累积质量。
- `blank_footprint` 空白复用范围：反查每个空白点进入哪些数据，并分开空白与浓度状态。
- `threshold_review` 阈值观察范围：分开最早未排除和首次有证据越限，不推定真实越限时刻。
- `checkpoints` 独立池量复核：独立池量与取样后池量核对，不回填浓度或预测池量。
- `zero_draw_gaps` 缺测传播分类：缺测若没有取液只影响本次快照，有取液才传给以后。
