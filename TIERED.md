# 双站夹具分级复核

产线将控制用读数优先用于确定夹具接缝。生产读数用于核定控制证据允许的剩余变化，也要在同一组可实现的接缝和站内读数上计账。V1 流程、行格式、有理数规则和公共入口见 `README.md`。

## 修订和站件

- `ledger.revisions.record_revision` 新增关键字参数 `control_ids=None`。省略或传 `None` 时沿用 V1。显式声明接受普通观测行号的列表或元组。每个行号须属于本次普通观测且只出现一次，其余普通观测归生产组。显式空序列表示分级修订且控制组为空。控制组可包含全部普通观测。非法声明整次拒绝。
- `load_revision` 新增 `control_ids` 属性，旧式修订为 `None`，分级修订为按普通观测原序排列的控制行号元组。修订固定两组归属，更正另存新修订。`station_check` 沿用现有站内核账口径。
- `station.publish.freeze_tiered_station(db, revision_id, terminals)` 接收显式分级修订，沿用原端子校验和顺序，返回有 `artifact_id`、`trial_id`、`station`、`revision_id`、`unit` 和 `terminals` 的固定站件。分级修订使用该入口，`freeze_station` 对其报 `ValueError`。分级入口遇到 V1 修订也报 `ValueError`。
- 分级站件绑定原修订与有序端子，保全两级共用的私有状态，私有点名和原观测行留站。站件须足以让独立复核库在源账关闭后执行下述联合核定。继续用 `encode_station_artifact`、`decode_station_artifact` 和 `load_station_artifact` 传递和领取两类件。分级件沿用 `id` 与 `body` 的规范 JSON 封套和以正文计算的内容标识，`body.version` 为整数 `2`。分级证据的内部表示由实现决定。解码时核对版本、内容标识、规范编码、站点和来源字段、端子及证据结构，拒绝不合法的有理数、矛盾的站件硬条件和无效的残差表示。用同一修订及同序端子再次冻结，沿用原件编号和字节。

## 复核及定稿

`assembly.requests.prepare_comparison` 的调用参数沿用 V1。两件须为同版本、同试验、同单位、不同站。版本混用和坏件在准备时整次拒绝。任务保存原件、对应、参考定值及有序差值，`load_comparison_request` 可按号取回。

`review.reconcile.sign_comparison(db, request_id)` 按原接口签发。每站沿用原硬等式和原加权平方残差，只有明确绑定的端子才共享取值。分级任务先最小化两站控制残差之和，再在全部共同控制最优解中最小化两站生产残差之和。两个等级使用同一组接缝值，每站两个等级的账均来自该站同一次可实现的私有状态。空组的残差为零。差值继续按左减右，`None` 操作数代表原点。仅当差值在全部最终共同最优解上恒定时返回 `confirmed` 和该值，否则返回 `unknown` 和空值。顺序和重复请求均沿用 V1。

分级返回值保留 `result.issued` 和 `result.contrasts` 的原接口。`result.residuals.stations` 按入件顺序返回 `(站名, 控制残差, 生产残差)` 元组序列，另有 `control_total` 和 `production_total`，各等于对应分站账之和。残差、总账及已确认的差值用 `Fraction`。

分级报告 JSON 的 `version` 为 `2`，保留 V1 的 `request_id`、`name`、`trial_id`、`unit`、`artifact_ids` 与 `contrasts` 字段。`station_residuals` 按入件顺序列出对象，每个对象含 `station`、`control_residual`、`production_residual`。`total_residuals` 含 `control`、`production`。载荷中的有理值沿用整数或分数字符串。

共同不可行沿用 `JointInfeasibleError`，非法输入或载荷报 `ValueError`。未知试验、修订、站件和任务号沿用 `KeyError`，未知报告号沿用 `None`。非法或数据库失败时，修订、冻结、准备和签发各自整次无新增。定稿、原任务与两父件的关联、成功回执同次提交。传播 SQLite 写入或提交错误，修复提交条件后可按原任务重试。源账更正、复核库关闭重开后，`records.retrieve.get_comparison` 按原报告号直接读取保存的定稿字节、原父件关联和原回执。V1 接口、修订和载荷编码、旧站件与报告、旧库读写及全部原回归继续可用。

## 样例与核验

`python3 -B tiered_examples.py` 会用两份独立源账做 V1 对照。北站两份修订登记相同的 `NORTH_ROWS`。南站登记 `SOUTH_EXACT`，固定 B=1。两站只公开 `TERMINALS`，按 `BINDINGS` 绑定 B，按 `CONTRASTS` 查询北站 B 相对原点的值。两次 V1 定稿都是北站残差 `2/3`、南站残差 `0`、差值 `1`。

用相同输入验证分级链路时，登记北站两个修订分别使用 `CONTROL_GROUPS[0]` 和 `CONTROL_GROUPS[1]`，南站使用 `control_ids=[]`。三件分别按对应修订调用 `freeze_tiered_station`，编码并关闭源账。用原任务入口分别接纳两件北站载荷和同一南站载荷，然后按任务号签发。

| 北站控制组 | 北站控制、生产 | 南站控制、生产 | 控制、生产总账 | B |
| --- | --- | --- | --- | --- |
| `fixture_zero` | `0`、`2` | `0`、`0` | `0`、`2` | `confirmed 1` |
| `seam_read` | `0`、`1` | `0`、`0` | `0`、`1` | `confirmed 1` |

另可将南站硬等式换成等权控制读数 B=2，北站登记等权控制读数 B=0、等权生产读数 B=5，仍绑定两站的 B。应确认 B=1，控制分站账为 1、1，生产分站账为 16、0。若北站控制读数改为 Z=0、生产读数为 B−Z=2，并用零系数声明公开端子 D，南站仅声明自由的 B，则在只绑定 B 时应确认 B=2，D 相对于原点为 `unknown`，两级账均为零。

可在第一组样例中追加参考 `(("north", "B"), 2)` 核对共同不可行。提交失败可复用 `tests/test_records.py` 的 `test_commit_rollback` 中在回执写入后触发延迟外键失败的夹具，核对定稿、关联与回执的计数，再解除触发器重试。更正北站后重开复核库，按旧报告号核对定稿字节、两父件及回执。

沿用 `.pointwise-runtime.json` 的 `verify` 和 `demo` 入口。核验接通原回归和本次分级链路，业务断言失败以非零状态退出。演示用固定样例实际签发，展示等级互换后的两次账及更正、重开后的原号领取结果。
