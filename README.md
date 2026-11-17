# 中国社零月报修订查询器

2026 年 10 月 20 日写月报时，6 月社会消费品零售总额的季调环比该填多少？当时可查到 **0.40%**。11 月 16 日发布的新公报把同一个 6 月调为 **0.25%**。在复盘旧报告时，直接取最新值就会用上当时还看不到的修订。这里可以按指定日期查当时已经发布的值，也可以逐期对照每次修订的公报。

**数据引自国家统计局网站（www.stats.gov.cn）。** 数值来自各期公报的“主要数据”和附注“环比数据修订”。[10 月 19 日公报](https://www.stats.gov.cn/sj/zxfb/202610/t20261019_1965614.html) · [11 月 16 日公报](https://www.stats.gov.cn/sj/zxfb/202611/t20261116_1965839.html) · [数据使用与署名条款](https://www.stats.gov.cn/wzgl/202302/t20230217_1912857.html)

打开 [在线交互演示](https://tfy20030726-spec.github.io/china-stats-vintages/)，也可下载后双击 `index.html`。选择统计月份和查询日期，查看当时可见的数值及历次修订。`python demo/build.py` 从仓库内的 CSV 重新生成这份静态页面。

## 一分钟复现

Python 3.10 或以上，标准库即可。克隆仓库后，在根目录执行以下命令。查询和测试均可离线运行。

```shell
python stats.py as-of --period 2026-06 --on 2026-10-20
python stats.py as-of --period 2026-06 --on 2026-11-16
python stats.py revisions --period 2026-06
python -m unittest discover -v
```

前两个命令返回包含数值、发布日期和官方原文链接的 JSON。第三条输出逐个版本，每行一个 JSON。以 2026 年 6 月为例，可在对应公报附注的年份、月份行核对：

| 公报发布日 | 6 月季调环比 | 比上一归档版本变化 |
| --- | ---: | ---: |
| [2026-07-15](https://www.stats.gov.cn/sj/zxfb/202607/t20260715_1964127.html) | 0.38% | 首次收录 |
| [2026-08-17](https://www.stats.gov.cn/sj/zxfbhjd/202608/t20260817_1965052.html) | 0.35% | −0.03 个百分点 |
| [2026-09-15](https://www.stats.gov.cn/sj/zxfb/202609/t20260915_1965311.html) | 0.40% | +0.05 个百分点 |
| [2026-10-19](https://www.stats.gov.cn/sj/zxfb/202610/t20261019_1965614.html) | 0.40% | 0.00 个百分点 |
| [2026-11-16](https://www.stats.gov.cn/sj/zxfb/202611/t20261116_1965839.html) | 0.25% | −0.15 个百分点 |

## 查询口径

- `--period` 指统计月份。对于年初累计，填区间结束月份。`--on` 指北京时间当天结束时，以本档案已收录的公报为限。6 月的首次收录日是 7 月 15 日，查询 7 月 14 日会得到 `no_release_in_archive`。
- `retail_total` 是社会消费品零售总额，`online_goods` 是网上商品零售额。`mom_sa` 是经季节调整的月度环比增速，只收录社零总额。`yoy` 是公报直接给出的同比增速，`amount` 是金额。金额单位为亿元，增长率以百分数表示。
- `month` 是当月，`year_to_date` 是年初累计。2026 年 10 月社零同比为 **0.4%**，1—10 月累计同比为 **1.0%**。网上商品零售额只公布同期累计 **107274 亿元**，当月栏是横线。CSV 以空值保存横线，查询返回 `not_reported`，不会当成零。
- `revisions` 保留数值相同的相邻版本。`change` 表示相对上一个归档版本的差，增速用百分点、金额用亿元表示。首次收录或比较一侧缺失时返回 `null`。
- 公报附注说明统计范围调整可能影响同比基数。查询直接返回官方同比；示例没有用两年的公开绝对额重新估算同比。选用的网上商品零售额只含商品，与包含服务的网上商品和服务零售额口径不同。

```shell
python stats.py as-of --period 2026-10 --on 2026-11-16 --metric retail_total --scope year_to_date --measure yoy
python stats.py as-of --period 2026-10 --on 2026-11-16 --metric online_goods --scope month --measure amount
```

## 数据如何生成

[data/sources.csv](data/sources.csv) 列出每份公报的发布日期、报告期和官方网址。随仓库提供 2026 年 5 至 10 月报告期共六期数据。每期摘取主表两项指标各四个单元格，以及附注表连续十三个月的社零季调环比，共计 126 条观察记录。[data/observations.csv](data/observations.csv) 保存数值和逐行来源；较早观察月份可以只在修订表中出现。

```shell
python stats.py refresh
```

这条命令重新读取清单中的官方网页。导入时读取页面发布日期元数据，校验表头、年份和连续月份，核对桌面版和移动版的重复表。整批通过后才替换 CSV；网页结构变化、重复表不一致或已归档数值变化都会报错并保留已有文件。遇到同一公报事后更正，需要人工核对原文和变更时间。

新增一期时，先把兼容格式的国家统计局月报及其日期追加到来源清单，然后运行 `refresh` 及测试。现有提取器只支持这类同时提供当月／累计四列和十三个月修订表的公报。春节前后的 1—2 月合并报表需单独适配。档案通过回读官方历史公报建立，不能核实原网页在发布当日之后是否发生过未单独公告的编辑。

[数据表](data/observations.csv) 的复合键为 `release_date, period, metric, period_type, measure`。按日期查询会在符合键的行中取 `release_date <= on` 的最后一条。早于档案范围的查询不能据此推断国家统计局当时尚未发布过数据。

## 实现与参考

版本留存思路参考 [Simon Willison 的公开数据历史存档](https://github.com/simonw/ca-fires-history)。Python 提取器针对国家统计局月报编写，使用公报发布日期复原版本顺序。初版使用 OpenAI Codex 辅助实现、验证并编写说明。国家统计局保留源数据与网页内容的相关权利，摘录的统计数据适用其网站使用条款。
