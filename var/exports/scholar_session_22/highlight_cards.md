# 亮点引用证据报告

## 一、报告摘要

- 学者会话：Jingyi Ning
- 目标论文数量：1
- 报告卡片数量：5
- 强证据数量：3
- 普通引用数量：2
- 需要复核数量：5
- 误报已排除数量：5

## 二、强证据卡片

### 1. 方法采用：方法采用引用：MoiréVision: A Generalized Moiré-based Mechanism for 6-DoF Motion Sensing

**引用论文：** MoiréLens: Bringing Schlieren Imaging into Real-World Environments Using Moiré Patterns  
**发表位置：** unknown, 2026  
**被引用论文：** MoiréVision: A Generalized Moiré-based Mechanism for 6-DoF Motion Sensing  
**证据类型：** 方法采用 / 方法采用  
**证据强度：** strong  
**人工复核建议：** 需要复核  

### 原文证据

> MoiréPose targets 6-DoF localization [19], and **MoiréVision** **extends this concept** to **curvilinear patterns with sub-pixel feature** extraction **[20]**.

### 原文上下文

> butions in this work: •We present MoiréLens, a Moiré-based Schlieren imaging frame- work that replaces traditional optical assemblies with high- frequency fringe backgrounds and commodity cameras, enabling low-cost, high-sensitivity, extended-range, and robust Schlieren imaging in real-world environments. 1275 MoiréLens: Bringing Schlieren Imaging **into Real-World Environments Using Moiré Patterns** SenSys ’26, May 11–14, 2026, Saint Malo, France •We develop AutoMoiré, an automatic calibration and control module that continuously maintains geometric alignment and stable Moiré formation under varying camera viewpoints. •We design a human-invisible background embedding **and adap- tive Moiré-to-Schlieren conversion pipeline** that integrates near- invisible fringes into wallpapers and extracts Moiré distortions with tunable spatial–temporal sensitivity. •We demonstrate that MoiréLens effectively reconstructs thermal and gaseous flows using only commodity cameras and lightweight image processing, supporting diverse real-world applications such as gas-leak localization, HVAC monitoring and cooking automation. 2 **Related Work Sensing Using Moiré Patterns** : Moiré patterns have been used in visual sensing because small geometric displacements yield large, measurable phase shifts in the fringes [5, 19–22, 33, 36, 37]. Existing designs typically generate Moiré patterns in two ways: (i) Tag-based (stacked gratings). Two high-frequency gratings are rigidly stacked on a passive marker to ...

### 亮点评价

《MoiréLens: Bringing Schlieren Imaging into Real-World Environments Using Moiré Patterns》（2026）在“2 Related Work”中通过 [20] 将《MoiréVision: A Generalized Moiré-based Mechanism for 6-DoF Motion Sensing》作为方法来源或方法基础，具体涉及 MoiréVision / extends this concept / curvilinear patterns / sub-pixel feature extraction / curvilinear patterns with sub-pixel feature，说明目标论文的技术路线已进入后续研究的方法链路。

### 评价理由

证据位于“2 Related Work”上下文中。原文包含目标引用编号 [20]，可将该段与被引论文建立锚点关系。原文中的关键短语包括：MoiréVision / extends this concept / curvilinear patterns / sub-pixel feature extraction / curvilinear patterns with sub-pixel feature。因此判断为方法采用：该段将目标论文关联到后续方法设计、技术流程或实现依据。

### 风险提示

如该段为成组引用，需要人工确认归因范围。

<!-- Citing paper: MoiréLens: Bringing Schlieren Imaging into Real-World Environments Using Moiré Patterns; Evidence quote: MoiréPose targets 6-DoF localization [19], and MoiréVision extends this concept to curvilinear patterns with sub-pixel feature extraction [20].; Evidence reason: 证据位于“2 Related Work”上下文中。原文包含目标引用编号 [20]，可将该段与被引论文建立锚点关系。原文中的关键短语包括：MoiréVision / extends this concept / curvilinear patterns / sub-pixel feature extraction / curvilinear patterns with sub-pixel feature。因此判断为方法采用：该段将目标论文关联到后续方法设计、技术流程或实现依据。; card_type: 方法采用; anchor_validation_status: valid_grouped; anchor_validation_reason: citation_text_contains_target_marker -->

### 2. 代表性相关工作：代表性相关工作：MoiréVision: A Generalized Moiré-based Mechanism for 6-DoF Motion Sensing

**引用论文：** RetroLiDAR: A Liquid-crystal Fiducial Marker System for High-fidelity Perception of Embodied AI  
**发表位置：** unknown, 2025  
**被引用论文：** MoiréVision: A Generalized Moiré-based Mechanism for 6-DoF Motion Sensing  
**证据类型：** 代表性相关工作 / 代表性相关工作  
**证据强度：** moderate  
**人工复核建议：** 需要复核  

### 原文证据

> Beyond the conventional marker systems that utilize RGB cameras to read printed markers, recent research has explored more advanced hardware designs to achieve additional functionalities such as single-pixel imaging for privacy-preserving reading [73], leveraging the optical image stabilization module of a smartphone camera to reconstruct 3D images [74], utilizing the dual cameras on **mobile devices for depth estimation** [75], **designing Moiré patterns** for **marker pose measurement** [76, 77], using birefringent nature of retroreflective tags for accurate angular measurement [78, 79], and designing 3D markers [80] or LED beacons [81] for underwater navigation.

### 原文上下文

> is the insuffi- cient frame rate, which leads to blurred reception of **LiDAR signals** during movement. Increasing the frame rate, which is currently constrained by the capabilities of commercial devices, would sig- nificantly mitigate the impact of mobility on system performance. 9 RELATED WORK Visual Fiducial Markers. Visual fiducial markers are artificial landmarks designed to serve two primary functions using cameras: identification (∼10 bits information) **and position estimation**. Var- ious types of markers have been proposed, such as ARTag [ 10], AprilTag [11], ArUco [12], ChromaTag [63], and STag [64]. They have a broad range of applications including augmented reality [65], robot navigation [66, 67], drone landing [68, 69], large-scale 3D printing [70], surgery [71], **and animal behavior tracking** [72]. Beyond the conventional marker systems that utilize RGB cam- eras to read printed markers, recent research has explored more advanced hardware designs to achieve additional functionalities such as single-pixel imaging for privacy-preserving reading [73], leveraging the optical image stabilization module of a smartphone camera to reconstruct 3D images [74], utilizing the dual cameras on **mobile devices for depth estimation** [75], **designing Moiré patterns** for **marker pose measurement** [76, 77], using birefringent nature of retroreflective tags for accurate angular measurement [78, 79], and designing 3D markers [80] or LED beacons [81] for underwater navigation. RetroLiDAR extends ...

### 亮点评价

《RetroLiDAR: A Liquid-crystal Fiducial Marker System for High-fidelity Perception of Embodied AI》（2025）在“Beyond the conventional marker systems that utilize RGB cam-”中将《MoiréVision: A Generalized Moiré-based Mechanism for 6-DoF Motion Sensing》纳入后续技术路线梳理，并提到 Moiré patterns / marker pose measurement / 76 / 77 / mobile devices for depth estimation。这说明目标论文已进入该方向的技术脉络，但原文没有给出直接性能评价或高度赞扬。 该证据宜表述为相关工作引用或技术脉络引用，不宜表述为直接正向赞扬。 风险提示：这是成组引用，需要人工确认归因范围。 这不是直接正向评价，不应包装成直接正向赞扬。

### 评价理由

证据位于“Beyond the conventional marker systems that utilize RGB cam-”上下文中。原文包含目标引用编号 [77]，可将该段与被引论文建立锚点关系。原文中的关键短语包括：Moiré patterns / marker pose measurement / 76 / 77 / mobile devices for depth estimation。因此判断为代表性相关工作：该段体现目标论文被纳入相关工作或技术路线梳理，但不是直接直接正向赞扬。该证据来自成组引用，不能自动断言所有评价均唯一归属于目标论文。

### 风险提示

这是成组引用，需要人工确认归因范围。 这不是直接正向评价，不应包装成直接正向赞扬。

<!-- Citing paper: RetroLiDAR: A Liquid-crystal Fiducial Marker System for High-fidelity Perception of Embodied AI; Evidence quote: Beyond the conventional marker systems that utilize RGB cameras to read printed markers, recent research has explored more advanced hardware designs to achieve additional functionalities such as single-pixel imaging for privacy-preserving reading [73], leveraging the optical image stabilization module of a smartphone camera to reconstruct 3D images [74], utilizing the dual cameras on mobile devices for depth estimation [75], designing Moiré patterns for marker pose measurement [76, 77], using birefringent nature of retroreflective tags for accurate angular measurement [78, 79], and designing 3D markers [80] or LED beacons [81] for underwater navigation.; Evidence reason: 证据位于“Beyond the conventional marker systems that utilize RGB cam-”上下文中。原文包含目标引用编号 [77]，可将该段与被引论文建立锚点关系。原文中的关键短语包括：Moiré patterns / marker pose measurement / 76 / 77 / mobile devices for depth estimation。因此判断为代表性相关工作：该段体现目标论文被纳入相关工作或技术路线梳理，但不是直接直接正向赞扬。该证据来自成组引用，不能自动断言所有评价均唯一归属于目标论文。; card_type: 代表性相关工作; anchor_validation_status: valid_grouped; anchor_validation_reason: citation_text_contains_target_marker -->

### 3. 代表性相关工作：代表性相关工作：MoiréVision: A Generalized Moiré-based Mechanism for 6-DoF Motion Sensing

**引用论文：** MoiréLens: Bringing Schlieren Imaging into Real-World Environments Using Moiré Patterns  
**发表位置：** unknown, 2026  
**被引用论文：** MoiréVision: A Generalized Moiré-based Mechanism for 6-DoF Motion Sensing  
**证据类型：** 代表性相关工作 / 代表性相关工作  
**证据强度：** moderate  
**人工复核建议：** 需要复核  

### 原文证据

> **Single high-frequency grid ×camera CFA**. Interference between a camera CFA and a high-frequency **grid background enables ultra-precise pose estimation** **and tracking** [19–21]. MoiréPose targets 6-DoF localization [19], and **MoiréVision** **extends this concept** to **curvilinear patterns with sub-pixel feature** extraction **[20]**. MoiréVib demodulates periodic fringe motion for micro-vibration sensing [21].

### 原文上下文

> butions in this work: •We present MoiréLens, a Moiré-based Schlieren imaging frame- work that replaces traditional optical assemblies with high- frequency fringe backgrounds and commodity cameras, enabling low-cost, high-sensitivity, extended-range, and robust Schlieren imaging in real-world environments. 1275 MoiréLens: Bringing Schlieren Imaging **into Real-World Environments Using Moiré Patterns** SenSys ’26, May 11–14, 2026, Saint Malo, France •We develop AutoMoiré, an automatic calibration and control module that continuously maintains geometric alignment and stable Moiré formation under varying camera viewpoints. •We design a human-invisible background embedding and adap- tive Moiré-to-Sch**lieren conversion pipeline** that integrates near- invisible fringes into wallpapers and extracts Moiré distortions with tunable spatial–temporal sensitivity. •We demonstrate that MoiréLens effectively reconstructs thermal and gaseous flows using only commodity cameras and lightweight image processing, supporting diverse real-world applications such as gas-leak localization, HVAC monitoring and cooking automation. 2 Related Work Sensing Using Moiré Patterns : Moiré patterns have been used in visual sensing because small geometric displacements yield large, measurable phase shifts in the fringes [5, 19–22, 33, 36, 37]. Existing designs typically generate Moiré patterns in two ways: (i) Tag-based (stacked gratings). Two high-frequency gratings are rigidly stacked on a passive marker to ...

### 亮点评价

《MoiréLens: Bringing Schlieren Imaging into Real-World Environments Using Moiré Patterns》（2026）在 Related Work 中将《MoiréVision: A Generalized Moiré-based Mechanism for 6-DoF Motion Sensing》纳入后续技术路线梳理，并提到 Single high-frequency grid ×camera CFA / MoiréVision / extends this concept / curvilinear patterns / grid background enables ultra-precise pose estimation。这说明目标论文已进入该方向的技术脉络，但原文没有给出直接性能评价或高度赞扬。 原文中可直接核验的相关表述包括“vibration sensing / micro-vibration”。 该证据宜表述为相关工作引用或技术脉络引用，不宜表述为直接正向赞扬。 风险提示：这是成组引用，需要人工确认归因范围。 这不是直接正向评价，不应包装成直接正向赞扬。

### 评价理由

证据位于“2 Related Work”上下文中。原文包含目标引用编号 [20]，可将该段与被引论文建立锚点关系。原文中的关键短语包括：Single high-frequency grid ×camera CFA / MoiréVision / extends this concept / curvilinear patterns / grid background enables ultra-precise pose estimation。因此判断为代表性相关工作：该段体现目标论文被纳入相关工作或技术路线梳理，但不是直接直接正向赞扬。若用于精度/传感能力佐证，原文明确出现：vibration sensing / micro-vibration。该证据来自成组引用，不能自动断言所有评价均唯一归属于目标论文。

### 风险提示

这是成组引用，需要人工确认归因范围。 这不是直接正向评价，不应包装成直接正向赞扬。

<!-- Citing paper: MoiréLens: Bringing Schlieren Imaging into Real-World Environments Using Moiré Patterns; Evidence quote: Single high-frequency grid ×camera CFA. Interference between a camera CFA and a high-frequency grid background enables ultra-precise pose estimation and tracking [19–21]. MoiréPose targets 6-DoF localization [19], and MoiréVision extends this concept to curvilinear patterns with sub-pixel feature extraction [20]. MoiréVib demodulates periodic fringe motion for micro-vibration sensing [21].; Evidence reason: 证据位于“2 Related Work”上下文中。原文包含目标引用编号 [20]，可将该段与被引论文建立锚点关系。原文中的关键短语包括：Single high-frequency grid ×camera CFA / MoiréVision / extends this concept / curvilinear patterns / grid background enables ultra-precise pose estimation。因此判断为代表性相关工作：该段体现目标论文被纳入相关工作或技术路线梳理，但不是直接直接正向赞扬。若用于精度/传感能力佐证，原文明确出现：vibration sensing / micro-vibration。该证据来自成组引用，不能自动断言所有评价均唯一归属于目标论文。; card_type: 代表性相关工作; anchor_validation_status: valid_grouped; anchor_validation_reason: citation_text_contains_target_marker -->

## 三、代表性相关工作 / 普通引用

### 4. 代表性相关工作：代表性相关工作：MoiréVision: A Generalized Moiré-based Mechanism for 6-DoF Motion Sensing

**引用论文：** Visual-Based Out-of-Plane Rotation Measurement Using 3-D Moiré-Based Marker  
**发表位置：** IEEE Transactions on Instrumentation and Measurement, 2025  
**被引用论文：** MoiréVision: A Generalized Moiré-based Mechanism for 6-DoF Motion Sensing  
**证据类型：** 代表性相关工作 / 代表性相关工作  
**证据强度：** weak  
**人工复核建议：** 需要复核  

### 原文证据

> Some **methods leverage** the **aliasing eﬀect** [15], [16], **[17]**, which arises when a camera captures a target with a **periodic pattern** whose frequency closely matches the camera’s color ﬁlter array.

### 原文上下文

> t **mainly includes feature-based methods** [8] **and deep learning-based methods** [11]. The out-of-plane rotation measurement is more challenging than the in-plane one because the images of the target before and after rotation have a signiﬁcantly smaller di ﬀerence (see the top-right of each picture in Fig. 1). **Traditional methods** use the perspective-from-n-points (PnP) [12] or correlation- based [13] algorithms, which determine the angle based on **several visual features** on the target. However, compared to in-plane rotation, **these features** barely move in the image as they primarily change in depth, thus the accuracy is unsatisfactory. There are more e ﬀective methods for out-of-plane rotation measurement, **which usually involve new imaging models**. For instance, Gu et al. [14] designed a meta-surface composed of an array of blocks, each exhibiting a unique reﬂective property. Under illumination, the meta-surface has a shim- mering grayscale variation, which is sensitive to out-of-plane rotation. Some drawbacks hinder the practicality of this method. First, the meta-surface is di ﬃcult to manufacture. Second, its deployment is complicated by the need for a controlled light source, speciﬁc measurement conditions, and a complex calibration process. Some **methods leverage** the aliasing e ﬀect [15], [16], **[17]**, which arises when a camera 1557-9662 © 2025 IEEE. All rights reserved, including rights for text and data mining, and training of artiﬁcial intelligence and similar technologies. ...

### 亮点评价

《Visual-Based Out-of-Plane Rotation Measurement Using 3-D Moiré-Based Marker》（IEEE Transactions on Instrumentation and Measurement / 2025）在“Second, its deployment is complicated by the need for a”中将《MoiréVision: A Generalized Moiré-based Mechanism for 6-DoF Motion Sensing》纳入后续技术路线梳理，并提到 aliasing eﬀect / methods leverage / Some methods / periodic pattern / which usually involve new imaging models。这说明目标论文已进入该方向的技术脉络，但原文没有给出直接性能评价或高度赞扬。 该证据宜表述为相关工作引用或技术脉络引用，不宜表述为直接正向赞扬。 风险提示：这是成组引用，需要人工确认归因范围。 这不是直接正向评价，不应包装成直接正向赞扬。

### 评价理由

证据位于“Second, its deployment is complicated by the need for a”上下文中。原文包含目标引用编号 [17]，可将该段与被引论文建立锚点关系。原文中的关键短语包括：aliasing eﬀect / methods leverage / Some methods / periodic pattern / which usually involve new imaging models。因此判断为代表性相关工作：该段体现目标论文被纳入相关工作或技术路线梳理，但不是直接直接正向赞扬。该证据来自成组引用，不能自动断言所有评价均唯一归属于目标论文。

### 风险提示

这是成组引用，需要人工确认归因范围。 这不是直接正向评价，不应包装成直接正向赞扬。

<!-- Citing paper: Visual-Based Out-of-Plane Rotation Measurement Using 3-D Moiré-Based Marker; Evidence quote: Some methods leverage the aliasing eﬀect [15], [16], [17], which arises when a camera captures a target with a periodic pattern whose frequency closely matches the camera’s color ﬁlter array.; Evidence reason: 证据位于“Second, its deployment is complicated by the need for a”上下文中。原文包含目标引用编号 [17]，可将该段与被引论文建立锚点关系。原文中的关键短语包括：aliasing eﬀect / methods leverage / Some methods / periodic pattern / which usually involve new imaging models。因此判断为代表性相关工作：该段体现目标论文被纳入相关工作或技术路线梳理，但不是直接直接正向赞扬。该证据来自成组引用，不能自动断言所有评价均唯一归属于目标论文。; card_type: 代表性相关工作; anchor_validation_status: valid_grouped; anchor_validation_reason: citation_text_contains_target_marker -->

### 5. 代表性相关工作：代表性相关工作：MoiréVision: A Generalized Moiré-based Mechanism for 6-DoF Motion Sensing

**引用论文：** SpaceSched: A Constellation-Wide Scheduling System for Resolving Ground Track Congestion in Remote Sensing  
**发表位置：** unknown, 2025  
**被引用论文：** MoiréVision: A Generalized Moiré-based Mechanism for 6-DoF Motion Sensing  
**证据类型：** 代表性相关工作 / 代表性相关工作  
**证据强度：** weak  
**人工复核建议：** 需要复核  
**重要作者：** Tao Gu（IEEE Fellow）  

### 原文证据

> **In-orbit edge computing** has emerged to move the computation paradigm from various **ground embedded devices** [13, 23, 46, 55, 56, 60, 64, 75] to satellites.

### 原文上下文

> ... the spotlight mode. computationally intensive optimization tasks in advance and periodically to render minimal latency. Satellites in space efficiently execute the received commands and per- form the queue regulator. Furthermore,**SpaceSched enables fault-tolerant operation** through confidence-based restart capability, regardless of which side encounters an issue. Such responsive, efficient, and resilient design shows signif- icant potential in real-world deployment. 9 RELATED WORK Satellite networking. Recent advancements in satellite networking include but not limited to in-orbit edge com- puting [10, 15, 18, 49], ground station design [19, 25, 67, 72], networking protocols [8, 40, 43, 48, 61, 81], and security & privacy concerns [24, 50]. **In-orbit edge computing** has emerged to move the computation paradigm from various **ground embedded devices** [13, 23, 46, 55, 56, 60, 64, 75] to satellites. Specifically, Orbital Edge Computing (OEC) [16] is first proposed to **organize satellite constellations into computational pipelines**. Serval [69] relies on a bifurcated query execution that uses glacial filters to obtain relatively still boundaries from ground stations, and dynamic filters toquery rapidly changing objects fromsatellites. Regarding ground station infrastructure design, PMSat [58] utilizes a phased array-coupled passive meta-surface t

### 亮点评价

Tao Gu（IEEE Fellow）团队在《SpaceSched: A Constellation-Wide Scheduling System for Resolving Ground Track Congestion in Remote Sensing》（2025）在 Related Work 中将《MoiréVision: A Generalized Moiré-based Mechanism for 6-DoF Motion Sensing》纳入后续技术路线梳理，并提到 ground embedded devices / in-orbit edge computing / satellites. olerant operation / SpaceSched enables fault-tolerant operation / organize satellite constellations into computational pipelines。这说明目标论文已进入该方向的技术脉络，但原文没有给出直接性能评价或高度赞扬。 该证据宜表述为相关工作引用或技术脉络引用，不宜表述为直接正向赞扬。 风险提示：这是成组引用，需要人工确认归因范围。 这不是直接正向评价，不应包装成直接正向赞扬。

### 评价理由

证据位于“9 RELATED WORK”上下文中。原文包含目标引用编号 [56]，可将该段与被引论文建立锚点关系。原文中的关键短语包括：ground embedded devices / in-orbit edge computing / satellites. olerant operation / SpaceSched enables fault-tolerant operation / organize satellite constellations into computational pipelines。因此判断为代表性相关工作：该段体现目标论文被纳入相关工作或技术路线梳理，但不是直接直接正向赞扬。该证据来自成组引用，不能自动断言所有评价均唯一归属于目标论文。

### 风险提示

这是成组引用，需要人工确认归因范围。 这不是直接正向评价，不应包装成直接正向赞扬。

<!-- Citing paper: SpaceSched: A Constellation-Wide Scheduling System for Resolving Ground Track Congestion in Remote Sensing; Evidence quote: In-orbit edge computing has emerged to move the computation paradigm from various ground embedded devices [13, 23, 46, 55, 56, 60, 64, 75] to satellites.; Evidence reason: 证据位于“9 RELATED WORK”上下文中。原文包含目标引用编号 [56]，可将该段与被引论文建立锚点关系。原文中的关键短语包括：ground embedded devices / in-orbit edge computing / satellites. olerant operation / SpaceSched enables fault-tolerant operation / organize satellite constellations into computational pipelines。因此判断为代表性相关工作：该段体现目标论文被纳入相关工作或技术路线梳理，但不是直接直接正向赞扬。该证据来自成组引用，不能自动断言所有评价均唯一归属于目标论文。; card_type: 代表性相关工作; anchor_validation_status: valid_grouped; anchor_validation_reason: citation_text_contains_target_marker -->

## 四、需要人工复核的候选

暂无。

## 五、已排除误报摘要

citation_text_contains_target_marker: 4；title_alias_anchor_found: 1
