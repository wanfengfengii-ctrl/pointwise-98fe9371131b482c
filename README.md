# 双站夹具位移校准台账

量测中心为精密装配产线提供夹具位移复核。北站、南站分别保存仪器读数与计量参考关系。独立复核员接收两站冻结件，在源站关闭后核定共同接缝。晚班交班员按报告号交付产线计量班。

## 一个工作日

1. 登记员以工单号登记规范单位及两站。用同一工单、单位和站点再次初始化，得到同一试验身份。
2. 两站分析员分别录入具名修订。更正引用本站原修订并生成新号，旧号与旧证据继续可用。
3. 站内先核对全部硬关系是否相容，再核算普通读数的最小加权平方残差。
4. 分析员选定有序公开端子，按指定修订签发固定站件。站件随端子顺序携带精确可行条件与条件残差证据。
5. 源站关闭。复核员提交两件、明确的跨站端子对应、参考定值和有序差值请求，得到固定复核任务号。
6. 复核员按任务号核定共同可行性与共同最优值。产线获得同一个最优接缝上的两个分站账、总账和差值确认状态。
7. 复核库在一个事务保存定稿字节、原任务与父件关系和成功回执。失败可用原任务重试。
8. 源站作出更正后，交班员重开复核库，按原报告号领取同一份定稿、两份原父件编号和成功回执。

## 计算口径

每行由唯一的 `id`、点名到有理系数的 `terms`、以及 `target` 组成。普通观测另有严格为正的 `weight`。硬等式要求系数与点值的点积等于目标。普通观测按 `weight * (点积 - target)²` 计账。批内行号在两类行之间也必须唯一。量值按该试验规范单位录入，系统核对单位是否完全相等。整数、有理数字符串和 `Fraction` 可直接输入，浮点数和布尔值会被拒绝。零系数项可以声明一个自由测点。空硬条件不增加等式，空普通观测的残差为零。

固定件对每组公开取值先判断可行性，再计算可行时对私有点最小化后的残差。私有点名和原观测行留在源账。站件使用版本 1 的规范 JSON 字节和内容标识，接纳时核对表示、身份和结构。两件须来自同一试验、同一单位及不同站。只有明确对应的端子产生相等约束。空参考集合保留相应自由度，参考之间的矛盾在求解时拒发。

复核将两份站件与参考条件联立。共同最优值可由多组接缝值取得。仅当差值在所有共同最优解上恒定时返回 `confirmed` 和精确值，否则返回 `unknown` 和空值。差值按左操作数减右操作数，`None` 表示原点，仅表示取差的操作数。空差值请求返回空序列，重复项按原序返回。分站账在同一个共同最优接缝上计算，在整个共同最优解集上各自恒定。总账等于两站之和。持久载荷以整数或分数字符串记录有理值。

## Python 3.11 公开接口

在仓库根目录使用 Python 标准库运行。`ledger.store.open_ledger(path)` 打开源账，`assembly.store.open_review_store(path)` 打开独立复核库。接口负责提交自身的写入，调用方负责关闭连接。源站可用独立库登记相同工单信息，获得共同试验身份。

| 接口 | 调用及返回 |
| --- | --- |
| `ledger.trials.initialize_trial` | `initialize_trial(db, ticket, unit, stations)` 返回 `TrialRegistration`，含 `trial_id`。同工单已登记且单位或站点不同会被拒绝。 |
| `ledger.revisions.record_revision` | `record_revision(db, trial_id, station, unit, name, exact_rows, observations, parent_id=...)` 返回修订号。同试验本站内的修订名称唯一。两类行可省略，用 `load_revision(db, revision_id)` 读固定修订和父号。 |
| `station.fit.station_check` | `station_check(db, revision_id)` 返回含 `feasible` 与 `residual` 的站内核账结果。相矛盾的硬等式给出 `False` 和 `None`。 |
| `station.publish.freeze_station` | `freeze_station(db, revision_id, terminals)` 返回含 `artifact_id` 的 `StationArtifact`。用 `encode_station_artifact(artifact)` 取得可传递载荷，`decode_station_artifact(payload)` 离线解析，或从源账用 `load_station_artifact(db, artifact_id)` 取原件。`station.evidence.evaluate_boundary_evidence(artifact.evidence, values)` 按公开端子顺序返回条件残差或不可行的 `None`。 |
| `assembly.requests.prepare_comparison` | `prepare_comparison(db, first_payload, second_payload, bindings, references, contrasts, name=...)` 返回整数任务号。`bindings` 的每项为 `(第一件端子名, 第二件端子名)`，`references` 的每项为 `((站名, 端子名), 有理值)`，`contrasts` 的每项为 `(左操作数, 右操作数)`，操作数为 `(站名, 端子名)` 或 `None`。三个序列可省略，用 `load_comparison_request(db, request_id)` 读回固定任务。 |
| `review.reconcile.sign_comparison` | `sign_comparison(db, request_id)` 返回 `ComparisonResult`，含 `residuals`、`contrasts` 及 `issued`。每次成功调用签发一个固定报告。 |
| `records.retrieve.get_comparison` | `get_comparison(db, report_id)` 返回 `IssuedReport`，含报告号、原载荷字节、原父件关系和原回执。找不到该号时返回 `None`。 |

未知试验、修订、站件和任务号使用 `KeyError`。非法单位、证据、站件和引用使用 `ValueError`。共同不可行抛出 `JointInfeasibleError`，数据库写入或提交出错时传播 SQLite 错误。被拒绝的修订、冻结、准备或签发不留下该次新增结果。报告与回执在提交成功后一起返回。

## 核验和演示

完整回归使用 `python3 -B check_project.py`。控制台物化时提供该入口，执行 `tests` 包下的完整 `unittest` 套件。回归覆盖重复初始化、非法批回滚、站内精确拟合、私有点消去、站件准入与复用、离线共同核定、浮动差值、有序重复、实际 SQLite 提交失败与重试、历史领取和未知报告。

演示运行 `python3 -B demo.py`。`samples/shift.json` 提供两站早班录入与中班核定要求，`samples/correction.json` 提供晚班前的源账更正。演示使用临时目录中的两个站账和一个独立复核库。在北站，`Z=A` 且 `B=Z+1`，复核定值 `A=0`，所以共同接缝 `B-A=1`。相对于两站对 B 的普通目标 2 和 3，分站残差为 1 和 4，总残差为 5。演示实际签发并打印报告，再更正北站、重开复核库和按原号领取。
