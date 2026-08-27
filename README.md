# KML/KMZ 样式同步工具——完整开发需求与实现方案

## 一、项目目标

开发一个独立的 Windows 桌面应用，用于将一个 KML/KMZ 工程中的图层样式，按照另一个标准 KML/KMZ 工程的样式进行批量同步。

程序不依赖 QGIS、AutoCAD、Google Earth。

最终打包为：

```text
KML_Style_Synchronizer.exe
```

用户双击 EXE 即可运行。

---

# 二、核心概念

程序有两个工程：

### A：待同步工程

A 是需要修改样式的 KML/KMZ 工程。

### B：标准模板工程

B 是样式模板。

**B 端只负责提供标准样式，不允许被修改。**

最终操作逻辑：

```text
A图层
   ↓
寻找对应的B图层
   ↓
读取B图层内部实际使用的Style
   ↓
确定B图层的“标准Style”
   ↓
把标准Style同步到A图层
   ↓
输出新的A工程
```

---

# 三、非常重要：B端的“样式比例”是什么意思

这里的比例不是 A/B 图层匹配概率。

例如：

```text
B：02 EX pole.kml

Style-001：820个要素
Style-002：180个要素
```

那么：

```text
Style-001 = 82%
Style-002 = 18%
```

程序必须选择：

```text
Style-001
```

作为这个 B 图层的标准样式。

也就是说：

> **B图层内部哪个Style实际被最多要素使用，就选择哪个Style作为该图层的标准Style。**

这个比例只用于：

**确定 B 图层内部的标准 Style。**

绝对不能用于：

**A/B 图层匹配。**

---

# 四、A/B图层匹配规则

A、B图层匹配主要依据：

1. 图层名称
2. 几何类型

其中：

## 几何类型是硬限制

必须先判断 Geometry Type。

支持：

```text
POINT
LINE
POLYGON
```

例如 B：

```text
02 EX pole
POINT
```

那么 A 端只能匹配：

```text
POINT
```

不能匹配：

```text
LINE
POLYGON
```

即使名称非常相似也不能匹配。

---

# 五、下拉选择也必须限制Geometry Type

例如当前 B：

```text
02 EX pole
POINT
```

那么左侧 A 下拉框只能出现 A 中的 POINT 图层。

不能出现：

```text
LINE
POLYGON
```

例如：

```text
A可选：

02 EX pole          POINT
04 EX JB            POINT
06 IMU              POINT
07 SDU              POINT
```

而：

```text
05 Cable Route      LINE
08 HUB Boundary     POLYGON
```

不能出现在该下拉框中。

---

# 六、B端显示顺序必须严格保持原始文件夹顺序

这是一个非常重要的要求。

B 工程读取以后：

> **必须严格按照 B 文件夹中的实际顺序展开。**

例如 B 文件夹实际顺序：

```text
01 Boundary
02 EX pole
04 EX JB
05 Cable Route
06 IMU
07 SDU
01 X Box
02 HUB Box
SUB Box
END BOX
04 TB Box
06 MPO
07 FAT Boundary
08 HUB Boundary
09 Distribution cable
10 Feeder cable
```

程序界面必须保持：

```text
01 Boundary
02 EX pole
04 EX JB
05 Cable Route
06 IMU
07 SDU
01 X Box
02 HUB Box
SUB Box
END BOX
04 TB Box
06 MPO
07 FAT Boundary
08 HUB Boundary
09 Distribution cable
10 Feeder cable
```

不能自行按照：

```text
字母
数字
Style ID
Geometry Type
```

重新排序。

---

# 七、A端按照B端顺序建立匹配表

界面应该以 B 为基准生成行。

例如：

```text
A待同步图层                    B标准图层

01 Boundary             →      01 Boundary
02 EX pole              →      02 EX pole
04 EX JB                →      04 EX JB
05 Cable Route          →      05 Cable Route
                         →      06 IMU
07 SDU                  →      07 SDU
```

也就是说：

> B端有多少图层，就建立多少行。

B端永远固定。

A端可以自动匹配，也可以人工修改。

---

# 八、自动匹配逻辑

建议采用以下优先级：

## 第1级：名称完全一致 + Geometry一致

例如：

```text
A：02 EX pole
B：02 EX pole

A Geometry：POINT
B Geometry：POINT
```

直接匹配。

---

## 第2级：标准化名称后匹配

处理：

```text
大小写
前后空格
扩展名
连续空格
```

例如：

```text
02 EX pole.kml
02 EX POLE
02 EX pole
```

可以认为名称一致。

可以使用：

```python
normalize_name()
```

统一处理。

---

## 第3级：无法匹配

如果没有可靠匹配：

```text
A：空
B：06 IMU
```

保持空白。

不要强行猜测。

---

# 九、不建议自动使用模糊匹配直接修改

不要出现：

```text
02 EX pole
```

自动匹配成：

```text
02 HUB Box
```

这种情况。

如果以后需要模糊匹配，可以仅用于：

```text
提示可能匹配
```

而不是自动确定。

第一版优先采用：

> **精确名称 + Geometry Type**

保证安全。

---

# 十、文件扫描方式

推荐：

```python
pathlib.Path.rglob()
```

递归扫描用户选择的文件夹。

支持：

```text
.kml
.kmz
```

例如：

```text
Project/
├── 01 Boundary/
│   └── 01 Boundary.kml
├── 02 EX pole/
│   └── 02 EX pole.kmz
├── 04 EX JB/
│   └── 04 EX JB.kml
└── 05 Cable Route/
    └── 05 Cable Route.kml
```

需要保留：

```text
相对路径
文件名
父文件夹
最后一级子文件夹名称
原始扫描顺序
```

---

# 十一、关于“图层名称”的定义

优先使用实际工程中的：

```text
最后一级子文件夹名称
```

作为图层显示名称。

如果 KML 本身就是一个图层文件，没有额外子文件夹，则：

```text
KML文件名去掉扩展名
```

作为图层名称。

例如：

```text
02 EX pole/
    02 EX pole.kml
```

显示：

```text
02 EX pole
```

如果：

```text
02 EX pole.kml
```

则同样显示：

```text
02 EX pole
```

建议内部保存：

```python
LayerInfo(
    name,
    file_path,
    relative_path,
    geometry_type,
    styles,
    feature_count,
    style_usage
)
```

---

# 十二、KML读取方式

建议使用：

```text
lxml.etree
```

不要只使用简单字符串替换 XML。

原因是 KML 存在 XML Namespace，例如：

```xml
<kml xmlns="http://www.opengis.net/kml/2.2">
```

还可能出现：

```text
gx:
atom:
xal:
```

所以 XML 必须使用 Namespace-aware 的方式解析。

核心函数建议：

```python
parse_kml()
```

以及：

```python
parse_kmz()
```

---

# 十三、KMZ处理

KMZ本质上是ZIP。

使用：

```python
zipfile.ZipFile
```

处理。

读取流程：

```text
KMZ
 ↓
ZipFile
 ↓
寻找doc.kml
 ↓
读取KML
 ↓
解析Style
```

同步后：

```text
修改KML
 ↓
保留KMZ内部其他资源
 ↓
重新ZIP
 ↓
输出新的KMZ
```

特别注意：

**不能因为修改Style而破坏KMZ中的图片、Icon、其他资源。**

例如：

```text
doc.kml
images/
    icon1.png
    icon2.png
files/
    xxx
```

这些都必须尽量原样保留。

---

# 十四、Geometry Type自动识别

每个图层解析时必须确定：

```text
POINT
LINE
POLYGON
```

建议通过实际KML Geometry元素统计。

例如：

```xml
<Point>
```

→ POINT

```xml
<LineString>
```

→ LINE

```xml
<Polygon>
```

→ POLYGON

如果存在：

```xml
<MultiGeometry>
```

则继续递归解析内部Geometry。

建议函数：

```python
detect_geometry_type()
```

内部递归：

```python
extract_geometries()
```

---

# 十五、Geometry Type不是根据Style猜测

不能：

```text
看到IconStyle
→ 判断POINT
```

应该：

```text
实际KML Geometry
→ 判断POINT / LINE / POLYGON
```

因为 Style 和 Geometry 是两个不同概念。

---

# 十六、B标准Style确定算法

对于每个B图层：

### 1. 统计所有Feature

读取：

```text
Placemark
```

统计每个Feature实际引用的：

```text
styleUrl
```

以及可能存在的：

```text
inline Style
```

---

### 2. 统计Style使用数量

例如：

```text
Style A = 820
Style B = 180
```

---

### 3. 计算比例

```python
ratio = style_count / total_feature_count
```

得到：

```text
Style A = 82%
Style B = 18%
```

---

### 4. 最大比例Style作为标准Style

```python
standard_style = max(style_usage)
```

即：

```text
Style A
```

---

# 十七、特殊情况：B只有一个Style

例如：

```text
Style A = 100%
```

直接使用。

---

# 十八、特殊情况：B没有Style

如果 B 图层没有任何可识别Style：

界面显示：

```text
Style：未找到
```

并且该行不能执行同步。

不能随便生成一个默认Style覆盖A。

---

# 十九、特殊情况：两个Style比例一样

例如：

```text
Style A = 50%
Style B = 50%
```

不要随机选择。

建议：

```text
状态：存在多个最高占比Style
```

让用户选择。

或者第一版直接：

```text
标记为“需人工确认”
```

这样最安全。

---

# 二十、样式同步范围

目标不是只同步颜色。

应该尽量完整复制 B 标准 Style 中与显示有关的内容。

## POINT

包括：

```text
IconStyle
    color
    scale
    heading
    Icon
        href

LabelStyle
    color
    scale
```

如果存在其他有效的 KML Style 属性，也应该保留。

---

## LINE

包括：

```text
LineStyle
    color
    width
```

以及相关显示属性。

---

## POLYGON

包括：

```text
PolyStyle
    color
    fill
    outline
```

同时处理：

```text
LineStyle
```

用于边界显示。

---

# 二十一、必须保留Style的透明度

KML颜色通常是：

```text
AABBGGRR
```

不是普通的：

```text
RRGGBB
```

因此：

```text
颜色
透明度
```

都必须完整保留。

例如：

```xml
<color>7d00ff00</color>
```

不能转换成：

```xml
<color>00ff00</color>
```

否则 Google Earth 显示会发生变化。

---

# 二十二、Icon处理要特别注意

如果 B：

```xml
<Icon>
    <href>icons/pole.png</href>
</Icon>
```

需要考虑 A 中是否存在对应图片。

因此建议把样式分为：

### 样式属性

```text
color
scale
width
fill
outline
label scale
label color
```

### 资源引用

```text
Icon href
```

第一版建议：

> **如果 B 的 Icon href 是外部/内嵌资源，则同步Style时同时同步引用关系，并检查A工程中是否存在该资源。**

如果资源不存在，界面给出警告：

```text
⚠ A工程中未找到B标准图标资源
```

不能静默失败。

---

# 二十三、styleUrl处理

KML中可能出现：

```xml
<styleUrl>#style001</styleUrl>
```

也可能：

```xml
<styleUrl>other.kml#style001</styleUrl>
```

必须正确解析。

建议建立：

```python
StyleRepository
```

负责：

```text
Style ID
→ Style XML
```

映射。

---

# 二十四、推荐内部数据结构

建议：

```python
class LayerInfo:
    name: str
    file_path: str
    relative_path: str
    geometry_type: str
    feature_count: int
    styles: dict
    standard_style_id: str | None
    standard_style_ratio: float
```

Style：

```python
class StyleInfo:
    style_id: str
    xml_element: etree.Element
    usage_count: int
    usage_ratio: float
    geometry_type: str
```

A/B匹配：

```python
class LayerMapping:
    a_layer: LayerInfo | None
    b_layer: LayerInfo
    geometry_type: str
    match_status: str
```

---

# 二十五、GUI推荐使用PySide6

界面建议：

```text
PySide6
```

不要使用Tkinter。

原因：

```text
界面更现代
QTableWidget/QTableView方便
下拉框方便
进度条方便
TreeView方便
后期扩展容易
```

---

# 二十六、主界面

建议：

```text
┌──────────────────────────────────────────────────────────────┐
│                 KML / KMZ STYLE SYNCHRONIZER                │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│ A 待同步文件夹： [________________________] [选择]           │
│ B 标准模板文件夹：[________________________] [选择]           │
│                                                              │
│ [扫描工程]       [自动匹配]                                  │
│                                                              │
├──────────────────────────────────────────────────────────────┤
│ A 待同步图层       │ B 标准图层       │ Geometry │ Style      │
├────────────────────┼──────────────────┼──────────┼────────────┤
│ 01 Boundary        │ 01 Boundary      │ POLYGON  │ 82%        │
│ 02 EX pole         │ 02 EX pole       │ POINT    │ 82%        │
│ 04 EX JB           │ 04 EX JB         │ POINT    │ 82%        │
│ 05 Cable Route     │ 05 Cable Route   │ LINE     │ 82%        │
│ [未匹配]           │ 06 IMU           │ POINT    │ 82%        │
│ 07 SDU             │ 07 SDU           │ POINT    │ 82%        │
├──────────────────────────────────────────────────────────────┤
│ 状态：已匹配 15 / 16                                         │
│                                                              │
│ [重新匹配]                         [开始同步]                │
└──────────────────────────────────────────────────────────────┘
```

---

# 二十七、B端必须固定

B列：

```text
只读
```

不能让用户修改。

A列：

```text
可修改
```

用户可以通过ComboBox重新选择。

---

# 二十八、A下拉框过滤逻辑

假设B：

```text
02 EX pole
POINT
```

那么：

```python
get_compatible_a_layers("POINT")
```

只返回：

```text
A中的POINT图层
```

例如：

```text
02 EX pole
04 EX JB
06 IMU
07 SDU
```

然后放入：

```text
QComboBox
```

---

# 二十九、增加“空/不匹配”选项

A下拉框第一项：

```text
-- 不同步 --
```

这样用户可以主动取消某个匹配。

---

# 三十、同步前必须进行Validation

点击：

```text
开始同步
```

之前进行：

```python
validate_mappings()
```

检查：

### 检查1

A/B Geometry是否一致。

### 检查2

A/B文件是否存在。

### 检查3

B是否成功找到标准Style。

### 检查4

是否存在重复A图层被绑定到多个B图层。

建议：

> 一个A图层默认只能对应一个B图层。

如果重复：

```text
⚠ A图层“02 EX pole”已被多个B图层使用
```

要求确认。

---

# 三十一、同步不要直接覆盖原文件

强烈建议默认：

```text
原始A工程
      ↓
输出
      ↓
A_StyleSynced
```

例如：

```text
Project_A/
```

输出：

```text
Project_A_StyleSynced/
```

这样原始文件不会被破坏。

以后可以增加：

```text
□ 覆盖原文件
```

但第一版默认不要覆盖。

---

# 三十二、输出时保持原始目录结构

例如：

```text
A/
├── 01 Boundary/
│   └── 01 Boundary.kml
├── 02 EX pole/
│   └── 02 EX pole.kmz
└── 05 Cable Route/
    └── 05 Cable Route.kml
```

输出：

```text
A_StyleSynced/
├── 01 Boundary/
│   └── 01 Boundary.kml
├── 02 EX pole/
│   └── 02 EX pole.kmz
└── 05 Cable Route/
    └── 05 Cable Route.kml
```

**只修改Style，不改变工程结构。**

---

# 三十三、必须保留A原始业务数据

同步过程中：

```text
Name
Description
ExtendedData
coordinates
Geometry
Placemark
Folder
SchemaData
自定义字段
```

原则上全部保持A原来的内容。

只修改：

```text
Style相关内容
```

这是非常重要的。

---

# 三十四、不要把B的整个Placemark复制到A

错误做法：

```text
复制B Placemark
覆盖A Placemark
```

这样会破坏：

```text
A坐标
A名称
A属性
A业务数据
```

正确方式：

```text
读取B标准Style
        ↓
只把Style应用到A Feature
```

---

# 三十五、推荐的程序模块

建议不要把所有代码写在一个main.py。

目录：

```text
KML_Style_Synchronizer/
│
├── main.py
│
├── ui/
│   ├── main_window.py
│   ├── mapping_table.py
│   └── dialogs.py
│
├── core/
│   ├── kml_parser.py
│   ├── kmz_handler.py
│   ├── geometry_detector.py
│   ├── style_analyzer.py
│   ├── style_mapper.py
│   ├── style_sync.py
│   └── validator.py
│
├── models/
│   ├── layer_info.py
│   ├── style_info.py
│   └── mapping.py
│
└── utils/
    ├── file_utils.py
    └── logger.py
```

---

# 三十六、各模块推荐函数

## kml_parser.py

```python
parse_kml(path)
```

读取KML。

```python
parse_kml_bytes(data)
```

从内存读取KML。

```python
find_placemarks(root)
```

查找所有Placemark。

```python
find_styles(root)
```

查找所有Style。

---

## geometry_detector.py

```python
detect_geometry_type(placemark)
```

返回：

```text
POINT
LINE
POLYGON
MIXED
UNKNOWN
```

```python
extract_geometry_types(placemark)
```

递归处理MultiGeometry。

---

## style_analyzer.py

```python
collect_style_usage(root)
```

统计Style使用次数。

```python
calculate_style_ratios(style_usage)
```

计算比例。

```python
select_standard_style(style_usage)
```

选择B图层最高占比Style。

---

## style_mapper.py

```python
normalize_name(name)
```

标准化名称。

```python
match_layers(a_layers, b_layers)
```

执行自动匹配。

```python
get_compatible_a_layers(a_layers, geometry_type)
```

获得下拉框候选。

---

## style_sync.py

```python
sync_kml_styles(a_document, b_style)
```

执行KML样式同步。

```python
replace_style_reference(...)
```

处理styleUrl。

```python
copy_style_definition(...)
```

处理Style定义。

---

## kmz_handler.py

```python
read_kmz(path)
```

读取KMZ。

```python
extract_kmz(path, temp_dir)
```

解压。

```python
repack_kmz(temp_dir, output_path)
```

重新打包。

---

## validator.py

```python
validate_mapping(mapping)
```

验证A/B Geometry。

```python
validate_standard_styles(...)
```

检查B标准Style。

```python
validate_duplicate_mappings(...)
```

检查重复映射。

---

# 三十七、程序启动后的工作流程

完整流程：

```text
启动程序
   ↓
选择A文件夹
   ↓
选择B文件夹
   ↓
扫描A/B
   ↓
解析KML/KMZ
   ↓
建立LayerInfo
   ↓
检测Geometry
   ↓
解析B所有Style
   ↓
统计B Style使用比例
   ↓
选择B最高占比Style
   ↓
按照B原始文件夹顺序建立表格
   ↓
A/B自动匹配
   ↓
Geometry过滤
   ↓
显示匹配结果
   ↓
用户人工调整A下拉框
   ↓
Validation
   ↓
开始同步
   ↓
复制A工程
   ↓
只修改Style
   ↓
输出新的KML/KMZ
   ↓
生成完成报告
```

---

# 三十八、界面状态建议

每一行增加状态：

```text
✓ 自动匹配
✓ 手动匹配
⚠ 未匹配
⚠ Geometry不一致
⚠ B没有Style
⚠ 多个最高占比Style
```

例如：

```text
02 EX pole
→
02 EX pole
POINT
82%
✓ 自动匹配
```

---

# 三十九、同步完成后显示报告

例如：

```text
=================================
KML Style Synchronization Result
=================================

A Project:
D:\Project_A

B Template:
D:\Template_B

Total B Layers : 16
Matched        : 15
Unmatched      : 1

POINT          : 8
LINE           : 5
POLYGON        : 3

Synchronized   : 15
Skipped        : 1
Errors         : 0

Output:
D:\Project_A_StyleSynced
=================================
```

---

# 四十、日志

程序应该有日志窗口：

```text
[21:32:01] 开始扫描B工程
[21:32:02] 发现16个图层
[21:32:03] 解析02 EX pole
[21:32:03] Geometry = POINT
[21:32:03] Style count = 2
[21:32:03] Style A = 820 (82%)
[21:32:03] Style B = 180 (18%)
[21:32:03] Standard Style = Style A
[21:32:04] A/B自动匹配完成
[21:32:05] 开始同步
[21:32:08] 同步完成
```

方便以后排查问题。

---

# 四十一、第一版不要做的功能

为了保证第一版稳定，暂时不要加入：

```text
QGIS依赖
Google Earth API
AutoCAD
复杂模糊匹配
人工编辑Style
地图预览
在线地图
```

第一版只解决：

```text
文件夹选择
↓
KML/KMZ解析
↓
B Style分析
↓
B最高占比Style确定
↓
Geometry匹配限制
↓
A/B人工映射
↓
Style同步
↓
输出KML/KMZ
```

先把这个核心流程做到稳定。

---

# 四十二、最终产品定位

最终不是一个脚本，而是一个真正的桌面工具：

```text
KML Style Synchronizer
```

用户使用时不需要知道：

```text
XML
Style ID
styleUrl
KML namespace
KMZ
Python
```

用户只需要：

```text
① 选择A文件夹
② 选择B文件夹
③ 检查自动匹配
④ 必要时修改A侧下拉框
⑤ 点击“开始同步”
⑥ 得到新的A工程
```

---

# 四十三、最关键的设计原则

开发时必须严格遵守以下5条：

### 1. B是模板，绝不修改B

### 2. B显示顺序严格按照原始文件夹顺序

### 3. B内部Style比例只用于确定标准Style，不用于A/B匹配

### 4. Geometry Type是A/B匹配的硬约束

```text
POINT → POINT
LINE → LINE
POLYGON → POLYGON
```

### 5. 同步只改变A的Style，不改变A的业务数据、坐标和工程结构

---

# 四十四、推荐技术栈最终确定

```text
语言：
Python 3.12+

GUI：
PySide6

XML：
lxml

KML：
lxml + XML Namespace

KMZ：
zipfile

文件系统：
pathlib

名称匹配：
字符串标准化 + 精确匹配

数据模型：
dataclass

日志：
logging

打包：
PyInstaller
```

最终：

```text
Python
  ↓
PySide6
  ↓
KML/KMZ Parser
  ↓
Style Analyzer
  ↓
Geometry Detector
  ↓
Layer Mapper
  ↓
Style Synchronizer
  ↓
Output KML/KMZ
  ↓
PyInstaller
  ↓
KML_Style_Synchronizer.exe
```

开发时请优先完成核心解析和同步逻辑，再开发GUI。不要一开始把所有逻辑全部写进界面代码。
# KML_Style_Sync
Sync kml exe 
