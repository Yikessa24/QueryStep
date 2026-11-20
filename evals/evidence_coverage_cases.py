"""Frozen, authored SQL retrieval cases grouped by fact pair for paired evaluation."""

# Each question family tests two specific facts. The passage columns are manually
# reviewed answer keys, independent of the retriever's concept metadata.
FAMILIES = (
    ("left-count-star", "join", (
        ("left_join_unmatched", "未配对的左表行仍在结果中", ("left-join/preserves-left", "left-join/match-condition")),
        ("count_star", "COUNT(*) 统计含 NULL 的输出行", ("count/row-count",)),
    ), (
        "以会员为左表，有人从没买过东西。查出的结果里还有他吗？统计总结果行要不要把他算进去？",
        "LEFT JOIN 右边没有配对订单时，左边的用户行还在吗？COUNT(*) 会不会跳过它？",
        "把设备和报警日志左连接，没有报警的设备还会出现在报表吗？我给结果用 COUNT(*) 得到的总数包含它吗？",
        "学生从没参加活动，做 LEFT JOIN 后系统会丢掉这个人吗？再数所有结果行会发生什么？",
        "商品没匹配到销量明细，我想既知道商品行会不会保留，也知道星号计数会不会把那行算上。",
    )),
    ("left-count-column", "join", (
        ("left_join_unmatched", "左连接为未配对行保留左行并补空", ("left-join/preserves-left",)),
        ("count_column", "目标列为 NULL 时 COUNT(列) 跳过该行", ("count/column-count",)),
    ), (
        "用左连接查作者和作品，没发表过的人是否还有一条记录？COUNT(作品编号) 会把那条算进去吗？",
        "右表键是空的账户怎么会出现在 LEFT JOIN 结果里？我对右表主键做计数时它参与吗？",
        "仓库表做左连接后，一家没有货物明细的仓库为什么仍在列表，对明细主键计数为什么又没它？",
        "左连接时商店没有匹配的活动记录。商店行能否留下，以及 COUNT(活动号) 是否会计入？",
        "我看到左边项目还在，右边任务编号空着。这行从哪里来，数右边任务 ID 时要不要加一？",
    )),
    ("join-filter-count", "join", (
        ("join_predicate", "将右侧等值条件移到 WHERE 可能筛掉补空行", ("where-after-join/predicate-placement",)),
        ("count_star", "COUNT(*) 统计筛选后的结果行", ("count/row-count",)),
    ), (
        "把付款状态从 ON 移到 WHERE 后，没付款记录的账号为什么不见了？此时 COUNT(*) 计入谁？",
        "左连接里挪了右侧的限制，结果列表少了行。右侧 NULL 怎么参与 WHERE 判定，总行数又怎么计？",
        "我先在 ON 要求检验合格，现在挪到 WHERE。右边没有合格记录的样品会怎样，星号计数又会怎样？",
        "ON 中的右表条件挪到 WHERE，哪些空右表行不见了？COUNT(*) 看的是连接结果还是筛过的结果？",
        "门店和签到记录 LEFT JOIN，把已签到限制改写到 WHERE 后人变少了。给剩余结果数行的规则是什么？",
    )),
    ("null-compare-meaning", "join", (
        ("null_compare", "检查 NULL 应使用 IS NULL", ("null/compare",)),
        ("null_meaning", "NULL 表示未知或缺失，与 0 或空字符串不同", ("null/unknown",)),
    ), (
        "没填的金额和 0 一样吗？要查漏填的行，能把条件写成 = NULL 吗？",
        "为什么空字符串也算一个值？我应当用什么判断找出真正没有填的信息？",
        "有的温度填了零，有的格子是未知状态。如何区分它们，又如何用条件筛到未知的值？",
        "数据库里一个格子写 NULL 是什么意思，和空文本有何区别？判断它时能写等号吗？",
        "没有填写座位号能不能默认成 0？要单独找缺座位号的人，NULL 应该怎么比较？",
    )),
    ("count-comparison", "aggregate", (
        ("count_star", "COUNT(*) 逐行计数", ("count/row-count",)),
        ("count_column", "COUNT(列) 只统计非空值", ("count/column-count",)),
    ), (
        "表里有十行，三行没填写分数。COUNT(*) 和 COUNT(score) 分别依照什么规则加一？",
        "同一批结果里有空邮箱，为什么数所有结果行和数邮箱这一列会有差别？",
        "COUNT(备注) 和 COUNT(*) 谁统计所有行，谁会把备注 NULL 的几条排除？",
        "空订单号也在输出中。我要一个总行数和一个订单号非空的计数，两种 COUNT 怎么区分？",
        "两种聚合，一种是星号，一种传入实付金额列。如果有两条金额没填，两者分别统计什么？",
    )),
    ("group-boundary", "aggregate", (
        ("group_count", "GROUP BY 分别对每组聚合", ("grouping/group-count",)),
        ("having_boundary", "严格大于与大于等于在等于阈值时有区别", ("having/strict-inclusive",)),
    ), (
        "先把影片按类型汇总并计数。每一行代表什么？有一种刚好五部时，> 5 和 >= 5 怎么选？",
        "我要按分店分别数订单，如何得到每一组的总量？如果刚好三单，大于三与至少三有何区别？",
        "GROUP BY 后怎样知道每类有几条？用 HAVING 比较超过 8 条和到 8 条就算，有哪个边界？",
        "报表把报名按地区归到一起再数。在分组计数里，>= 和 > 对刚达到门槛的类别有什么影响？",
        "同类包裹怎样统计成每类一行？只留下至少四件与只留下超过四件，恰好四件会怎样？",
    )),
    ("where-having-boundary", "aggregate", (
        ("group_filter_order", "WHERE 先筛原始记录，HAVING 后筛聚合组", ("grouping/filter-order",)),
        ("having_boundary", "等于阈值的组只会通过 >= 而非 >", ("having/strict-inclusive",)),
    ), (
        "要先只看周末交易，再筛达到三笔的门店。两次筛选各在哪一步？恰好三笔会被 > 3 留下吗？",
        "WHERE 排除去年记录和 HAVING 应该谁在前？今年正好两条的类别要用 >= 2 还是 > 2？",
        "我想先删掉统计输入中未付款的行，再按门店过滤组；筛选恰好五单的门店要注意哪种比较？",
        "先挑红色产品，再保留产品数达到十的品牌。哪个条件放 WHERE，哪个放 HAVING？恰好十个怎么处理？",
        "HAVING 与 WHERE 分别作用在哪个阶段？对于刚好等于门槛的组，严格大于和大于等于产生什么差异？",
    )),
    ("join-same-preserves", "join", (
        ("join_same_result", "全部符合连接条件时两种放置可能同结果", ("where-after-join/matching-only",)),
        ("left_join_unmatched", "存在不匹配时左连接保留左行并补空", ("left-join/preserves-left", "left-join/match-condition")),
    ), (
        "我把订单条件搬到 WHERE，ON 和 WHERE 的结果竟相同。再加一个没配对的会员，左连接会先给出什么？",
        "为什么目前两种写法结果一样，如果下一批有个学生没有报名记录，左连接会怎么处理？",
        "每行都有一条有效订单所以两个结果一致吗？如果加一家没有符合条件的店，LEFT JOIN 会保留它吗？",
        "付款条件放 ON 和放 WHERE 在这批全匹配数据上看起来没区别。左表多一个未匹配账户时，左连接规则是什么？",
        "同样的数据里移动筛选位置啥也没变。要增加一个未配对的读者作为反例，他在左连接输出里是什么样？",
    )),
    ("distinct-null", "distinct", (
        ("distinct_null", "DISTINCT 判重时两个 NULL 视为相同", ("distinct/null",)),
        ("null_compare", "WHERE 中判断 NULL 应用 IS NULL", ("null/compare",)),
    ), (
        "DISTINCT 碰到两条 NULL 会合成一个吗？查询时可以写 WHERE 值 = NULL 吗？",
        "为什么去重将两个空值算一类，筛选空值却要写 IS NULL？分别是什么规则？",
        "我要让空邮箱的行去重，同时单独筛一份空邮箱列表。两个 NULL 去重算几个，WHERE 怎么写？",
        "先用 DISTINCT 对缺失的手机号判重，两个 NULL 会剩几条？要找缺失手机号又怎样比较？",
        "聚合前做 DISTINCT，两个空格子都会保留吗？假如只是筛出真正的 NULL，能用等号吗？",
    )),
    ("projection-distinct", "select", (
        ("projection_rows", "普通 SELECT 投影保留重复行", ("select-projection/rows",)),
        ("distinct_rows", "DISTINCT 按整条输出行去重", ("distinct/whole-row",)),
    ), (
        "我只 SELECT 顾客城市，两个顾客同城还会返回两行吗？加 DISTINCT 后怎么判重？",
        "投影只选编号和颜色会顺手删掉重复行吗？DISTINCT 是分别按列去重还是按组合？",
        "输出只要一列仓库名，两个订单同仓还剩几行？有了 DISTINCT 又会怎样？",
        "普通 SELECT 把其他列藏了，仍会看到两行同样数值吗？哪种规则把重复输出合成一行？",
        "两条记录选出来的城市和年龄完全相同。只做投影是否保留它们，DISTINCT 比哪个范围？",
    )),
    ("union-except", "set_ops", (
        ("union", "UNION 合并两边并去重", ("set-operations/union",)),
        ("except", "EXCEPT 保留左侧有而右侧无的值，方向有意义", ("set-operations/except",)),
    ), (
        "两个名单有重复客户。用 UNION 怎样组合？只想查旧名单有但新名单没有的人，EXCEPT 两边怎么放？",
        "UNION 会留下重复结果吗？如果改成 EXCEPT 并交换左右，为什么结果变了？",
        "我有两个授课表，想合并课程去重，也想看本学期开了但上学期没开的。两个集合写法怎么解释？",
        "UNION 与 EXCEPT 的输出怎么判定？特别是两张查询都存在的同一个编号。",
        "把本周和上周的商品名单合在一起能去重吗？只留上周有而本周没有的商品又怎么写？",
    )),
    ("exists-in", "subquery", (
        ("exists", "EXISTS 检查子查询是否返回至少一行", ("subqueries/exists",)),
        ("in", "IN 检查候选值是否出现在集合中", ("subqueries/in",)),
    ), (
        "子查询找到任意一条记录能用 EXISTS 吗？如果想判断学号属于子查询中的学号列表，该用什么思路？",
        "IN 和 EXISTS 都写在 WHERE 里，它们是比较值还是只验证子查询有没有行？",
        "按每位作者检查有没有作品，和把作者号放进作品作者号的名单里查，是分别在验证什么？",
        "用 EXISTS 时一定要返回具体值才算存在吗？IN 需要怎样的子查询结果来判定成员？",
        "怎样用一个子查询问『有记录吗』，再用另一个问『这个编号在名单里吗』？请讲清 EXISTS 和 IN。",
    )),
)

SINGLES = (
    ("join", "左连接里，右表没找到对应的人会怎么样？", ("left-join/preserves-left", "left-join/match-condition")),
    ("join", "为什么 AND 条件放在 ON 和 WHERE 位置时行数会有区别？", ("where-after-join/predicate-placement",)),
    ("aggregate", "恰好达到 HAVING 门槛时用大于等于是什么效果？", ("having/strict-inclusive",)),
    ("aggregate", "COUNT(*) 在结果里按什么计数？", ("count/row-count",)),
    ("null", "用 IS NULL 找到的是什么？", ("null/compare",)),
    ("distinct", "DISTINCT 遇到同一个颜色和尺寸怎么算重复？", ("distinct/whole-row",)),
    ("set_ops", "查左边有右边没有的记录，EXCEPT 里左右位置重要吗？", ("set-operations/except",)),
    ("subquery", "EXISTS 需要检查子查询至少返回几行？", ("subqueries/exists",)),
    ("where", "WHERE 对每行的判断是先还是后？", ("where-filter/matching", "grouping/filter-order")),
    ("conditions", "AND 和 OR 写一起用括号有什么作用？", ("conditions/precedence",)),
)

NO_ANSWER = (
    ("join", "查询明天成都的天气和地铁时刻表。"),
    ("aggregate", "HAVING 这个词在商务英语里的读音是什么？"),
    ("join", "用 MySQL JSON_TABLE 连接两个 JSON 数组。"),
    ("select", "如何给 SQLite 表做全文索引并配置中英文词典？"),
    ("subquery", "如何迁移 PostgreSQL WAL 归档到对象存储？"),
    ("where", "查询结果该如何发给微信机器人？"),
    ("conditions", "Python 调用 OpenCV 如何做图片缩放？"),
    ("aggregate", "并行索引为什么运行中卡住？"),
    ("join", "SQL SERVER 怎么分析锁等待的执行计划？"),
    ("null", "请用十组真实学生个人资料举例。"),
)
