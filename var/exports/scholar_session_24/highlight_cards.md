# 亮点引用证据报告

## 一、报告摘要

- 学者会话：Jingyi Ning
- 目标论文数量：1
- 报告卡片数量：14
- 强证据数量：8
- 普通引用数量：6
- 需要复核数量：14
- 误报已排除数量：11

## 二、强证据卡片

### 1. 理论基础：理论基础引用：MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern

**引用论文：** Moiré Spectral Augmentation and Masked Frequency Modeling for Document Presentation Attack Detection  
**发表位置：** IEEE Transactions on Dependable and Secure Computing, 2025  
**被引用论文：** MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern  
**证据类型：** 理论基础 / 理论基础  
**证据强度：** strong  
**人工复核建议：** 需要复核  

### 原文证据

> The second type of **MSPs** is generated due to **the frequency difference** (FD) between the pair of displaying and imaging devices in **the recapturing process** **[36]**.

### 原文上下文

> sampling, M periods of display pixels will appear in the captured image along the horizontal dimension of K pixels. Theoretical support for the phenomena mentioned above can be found in **the spectral model** in Section II-C. Speciﬁcally, the two-dimensional Dirac comb ∑ m,n δ(u−mp−nq)in **Eq. (3)** suggests the presence of **spectral peaks** at locations (mp,nq). However, due to the low pass property of the blurring ﬁlter in imaging devices [35], only the ﬁrst harmonic of the **spectral peaks** along the horizontal and vertical axes are chosen. Thus, we identify that the **MSPs** from display pixelation (DP) are located at Pdp =( mp,nq) where m,n ∈{ −1,0,1} and |m| ̸= |n|. In the experiment, we compute the 2D Discrete Fourier Transform (DFT) for obtaining ˆIc R(u). The locations of such **spectral peaks** can be computed from the parameters of display devices. Normalizing the image dimension to a unit length, **the spatial displaying vectors** can be deﬁned as a =( 1 M ,0) and b =( 0, 1 N ). Thus, **the spectral displaying vectors** can be computed by p = b×(a×b) ||a×b||2 =( M,0). Similarly, q =( 0,N ). III-A2) Moiré **Spectral Peaks** From **Frequency Difference**: The second type of **MSPs** is generated due to the frequency dif- ference (FD) between the pair of displaying and imaging devices in **the recapturing process** **[36]**. According to **Eq. (3)**, **the spectral model** shows a convolution operation between two Dirac comb Authorized licensed use limited to: Nanjing University. Downloaded on June 15,2026 at 14:14:17 UTC ...

### 亮点评价

《Moiré Spectral Augmentation and Masked Frequency Modeling for Document Presentation Attack Detection》（IEEE Transactions on Dependable and Secure Computing / 2025）在“The second type of MSPs is generated due to the frequency dif-”中通过 [36] 围绕 frequency difference / MSPs / recapturing process / the frequency difference / the recapturing process 展开建模/推导。这说明《MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern》中的相关方法或概念，被后续工作用于理论推导、模型解释或技术论证。

### 评价理由

证据位于“The second type of MSPs is generated due to the frequency dif-”上下文中。原文包含目标引用编号 [36]，可将该段与被引论文建立锚点关系。原文中的关键短语包括：frequency difference / MSPs / recapturing process / the frequency difference / the recapturing process。因此判断为理论基础：该段不是单纯列出参考文献，而是在正文技术论述中把目标论文作为建模、推导或概念说明的依据。

### 风险提示

如该段为成组引用，需要人工确认归因范围。

<!-- Citing paper: Moiré Spectral Augmentation and Masked Frequency Modeling for Document Presentation Attack Detection; Evidence quote: The second type of MSPs is generated due to the frequency difference (FD) between the pair of displaying and imaging devices in the recapturing process [36].; Evidence reason: 证据位于“The second type of MSPs is generated due to the frequency dif-”上下文中。原文包含目标引用编号 [36]，可将该段与被引论文建立锚点关系。原文中的关键短语包括：frequency difference / MSPs / recapturing process / the frequency difference / the recapturing process。因此判断为理论基础：该段不是单纯列出参考文献，而是在正文技术论述中把目标论文作为建模、推导或概念说明的依据。; card_type: 理论基础; anchor_validation_status: valid; anchor_validation_reason: citation_text_contains_target_marker -->

### 2. 理论基础：理论基础引用：MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern

**引用论文：** Moiré Backdoor Attack (MBA): A Novel Trigger for Pedestrian Detectors in the Physical World  
**发表位置：** ACM MM, 2023  
**被引用论文：** MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern  
**证据类型：** 理论基础 / 理论基础  
**证据强度：** strong  
**人工复核建议：** 需要复核  

### 原文证据

> When the two components (such as stripes, grids, waves, etc.) overlap, they produce shaded cross-stripes in the region of interference, with number and shape being dictated by the **geometry** and **relative position** of **the two similar patterns** [23, 42].

### 原文上下文

> ... vide a comparative analysis of the advantages and differ- ences of our proposed **MBA with existing backdoor attack methods** in the Table 1. Note that the term “Complex Physical Scenarios” specifically refers to a range of real-world scenarios, including in- door and outdoor environments, varying lighting conditions, differ- ent distances, and multiple viewing angles, which is closely related to the ability of triggers to be applied in the physical **world. 2.2 Moiré Effect Moiré pattern** is closely related to the physical phenomenon of interference [35]. It manifests as a striking visual effect resulting from the superposition of **two similar patterns** that exhibit periodic structures in space, usually in the form of black and white stripes [29]. When the two components (such as stripes, grids, waves, etc.) overlap, they produce shaded cross-stripes in the region of interference, with number and shape being dictated by the **geometry** and **relative position** of **the two similar patterns** [23, 42]. As they vary in frequency and degree of misalignment, a diverse array of **dynamic Moiré patterns** are created, as shown in Figure 2. The Moiré effect has achieved great success in many tasks, such as interferometry [ 25], navigation [32], steganography [34] and counterfeit prevention [1, 2]. In addition, Yue et al. [44] found that when utilizing a camera to capture an object, the sensor resolution may prove inadequate to precisely represent the repetitive details (a) Morié **patterns** in th

### 亮点评价

H Yu（IEEE Fellow）团队在《Moiré Backdoor Attack (MBA): A Novel Trigger for Pedestrian Detectors in the Physical World》（ACM MM / 2023）在“2.2 Moiré Effect”中通过 [23] 围绕 geometry / relative position / patterns / the two similar patterns / two similar patterns 展开建模/推导。这说明《MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern》中的相关方法或概念，被后续工作用于理论推导、模型解释或技术论证。

### 评价理由

证据位于“2.2 Moiré Effect”上下文中。原文包含目标引用编号 [23]，可将该段与被引论文建立锚点关系。原文中的关键短语包括：geometry / relative position / patterns / the two similar patterns / two similar patterns。因此判断为理论基础：该段不是单纯列出参考文献，而是在正文技术论述中把目标论文作为建模、推导或概念说明的依据。

### 风险提示

如该段为成组引用，需要人工确认归因范围。

<!-- Citing paper: Moiré Backdoor Attack (MBA): A Novel Trigger for Pedestrian Detectors in the Physical World; Evidence quote: When the two components (such as stripes, grids, waves, etc.) overlap, they produce shaded cross-stripes in the region of interference, with number and shape being dictated by the geometry and relative position of the two similar patterns [23, 42].; Evidence reason: 证据位于“2.2 Moiré Effect”上下文中。原文包含目标引用编号 [23]，可将该段与被引论文建立锚点关系。原文中的关键短语包括：geometry / relative position / patterns / the two similar patterns / two similar patterns。因此判断为理论基础：该段不是单纯列出参考文献，而是在正文技术论述中把目标论文作为建模、推导或概念说明的依据。; card_type: 理论基础; anchor_validation_status: valid_grouped; anchor_validation_reason: citation_text_contains_target_marker -->

### 3. 理论基础：理论基础引用：MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern

**引用论文：** MoiréEar: Moiré Can See What You Cannot Hear  
**发表位置：** unknown, 2026  
**被引用论文：** MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern  
**证据类型：** 理论基础 / 理论基础  
**证据强度：** strong  
**人工复核建议：** 需要复核  

### 原文证据

> The **spatial frequency** of **the resulting moiré pattern** is given by f_m = |f1 - f2| [1, 30, 31].

### 原文上下文

> es [ 26, 29, 42]. In recent years, new eavesdropping modalities based on wireless sensing have been proposed [5, 18, 38, 43, 44]. The core idea is to **use wireless signals**, such as millimeter waves, to sense minute vibrations caused by a speaker and thereby recover the acoustic content. While promising, the effective range of these systems remains very limited—typically only a few meters—making them impractical for stealthy eaves- dropping. Furthermore, **these methods** require the transmission of **dedicated signals** (e.g., **millimeter-wave signals**), which are de- tectable and therefore vulnerable to countermeasures. We propose, for the first time, to **employ moiré patterns** for eaves- dropping. The core idea lies in leveraging the strong amplification capability of **moiré patterns** to amplify tiny vibrations on everyday objects (e.g., a plastic box containing grapes) in our surrounding en- vironment. The underlying principle is that when two gratings with similar spatial frequencies overlap, small relative displacements are SenSys ’26, May 11–14, 2026, Saint Malo, France Zhang et al. Reference Grating **Moiré Pattern** Photodiode TargetBarcode Audio Source Figure 1: System overview of MoiréEar. optically amplified into a large, moving **moiré pattern**. Recent work, such as MoiréVib and MoiréPose [30, 31], has showcased the power of moiré amplification for motion sensing. Although prior work has demonstrated the power of moiré amplification, applying it to audio eavesdropping presents ...

### 亮点评价

《MoiréEar: Moiré Can See What You Cannot Hear》（2026）在“Audio Source”中通过 [30] 围绕 spatial frequency / moiré pattern / the resulting moiré pattern / moiré patterns / the moiré patterns 展开建模/推导。这说明《MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern》中的相关方法或概念，被后续工作用于理论推导、模型解释或技术论证。

### 评价理由

证据位于“Audio Source”上下文中。原文包含目标引用编号 [30]，可将该段与被引论文建立锚点关系。原文中的关键短语包括：spatial frequency / moiré pattern / the resulting moiré pattern / moiré patterns / the moiré patterns。因此判断为理论基础：该段不是单纯列出参考文献，而是在正文技术论述中把目标论文作为建模、推导或概念说明的依据。

### 风险提示

如该段为成组引用，需要人工确认归因范围。

<!-- Citing paper: MoiréEar: Moiré Can See What You Cannot Hear; Evidence quote: The spatial frequency of the resulting moiré pattern is given by f_m = |f1 - f2| [1, 30, 31].; Evidence reason: 证据位于“Audio Source”上下文中。原文包含目标引用编号 [30]，可将该段与被引论文建立锚点关系。原文中的关键短语包括：spatial frequency / moiré pattern / the resulting moiré pattern / moiré patterns / the moiré patterns。因此判断为理论基础：该段不是单纯列出参考文献，而是在正文技术论述中把目标论文作为建模、推导或概念说明的依据。; card_type: 理论基础; anchor_validation_status: valid_grouped; anchor_validation_reason: citation_text_contains_target_marker -->

### 4. 理论基础：理论基础引用：MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern

**引用论文：** MoiréEar: Moiré Can See What You Cannot Hear  
**发表位置：** unknown, 2026  
**被引用论文：** MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern  
**证据类型：** 理论基础 / 理论基础  
**证据强度：** strong  
**人工复核建议：** 需要复核  

### 原文证据

> its components along the X- and Y-axes can be represented as a **spatial frequency vector** **®𝐱_1** [1, 30, 31]: **®𝐱_1** = [f1 |cos θ1|, f1 |sin θ1|]^T.

### 原文上下文

> es [ 26, 29, 42]. In recent years, new eavesdropping modalities based on wireless sensing have been proposed [5, 18, 38, 43, 44]. The core idea is to **use wireless signals**, such as millimeter waves, to sense minute vibrations caused by a speaker and thereby recover the acoustic content. While promising, the effective range of these systems remains very limited—typically only a few meters—making them impractical for stealthy eaves- dropping. Furthermore, **these methods** require the transmission of **dedicated signals** (e.g., **millimeter-wave signals**), which are de- tectable and therefore vulnerable to countermeasures. We propose, for the first time, to **employ moiré patterns** for eaves- dropping. The core idea lies in leveraging the strong amplification capability of **moiré patterns** to amplify tiny vibrations on everyday objects (e.g., a plastic box containing grapes) in our surrounding en- vironment. The underlying principle is that when two gratings with similar spatial frequencies overlap, small relative displacements are SenSys ’26, May 11–14, 2026, Saint Malo, France Zhang et **al. Reference Grating Moiré Pattern** Photodiode TargetBarcode Audio Source Figure 1: System overview of MoiréEar. optically amplified into a large, moving moiré pattern. Recent work, such as MoiréVib and MoiréPose [30, 31], has showcased the power of moiré amplification for motion sensing. Although prior work has demonstrated the power of moiré amplification, applying it to audio eavesdropping presents ...

### 亮点评价

《MoiréEar: Moiré Can See What You Cannot Hear》（2026）在“Audio Source”中通过 [30] 围绕 spatial frequency vector / ®𝐱_1 / moiré patterns / the moiré patterns / use wireless signals 展开建模/推导。这说明《MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern》中的相关方法或概念，被后续工作用于理论推导、模型解释或技术论证。

### 评价理由

证据位于“Audio Source”上下文中。原文包含目标引用编号 [30]，可将该段与被引论文建立锚点关系。原文中的关键短语包括：spatial frequency vector / ®𝐱_1 / moiré patterns / the moiré patterns / use wireless signals。因此判断为理论基础：该段不是单纯列出参考文献，而是在正文技术论述中把目标论文作为建模、推导或概念说明的依据。

### 风险提示

如该段为成组引用，需要人工确认归因范围。

<!-- Citing paper: MoiréEar: Moiré Can See What You Cannot Hear; Evidence quote: its components along the X- and Y-axes can be represented as a spatial frequency vector ®𝐱_1 [1, 30, 31]: ®𝐱_1 = [f1 |cos θ1|, f1 |sin θ1|]^T.; Evidence reason: 证据位于“Audio Source”上下文中。原文包含目标引用编号 [30]，可将该段与被引论文建立锚点关系。原文中的关键短语包括：spatial frequency vector / ®𝐱_1 / moiré patterns / the moiré patterns / use wireless signals。因此判断为理论基础：该段不是单纯列出参考文献，而是在正文技术论述中把目标论文作为建模、推导或概念说明的依据。; card_type: 理论基础; anchor_validation_status: valid_grouped; anchor_validation_reason: citation_text_contains_target_marker -->

### 5. 理论基础：理论基础引用：MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern

**引用论文：** MoiréEar: Moiré Can See What You Cannot Hear  
**发表位置：** unknown, 2026  
**被引用论文：** MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern  
**证据类型：** 理论基础 / 理论基础  
**证据强度：** strong  
**人工复核建议：** 需要复核  

### 原文证据

> the combined **optical intensity** at position p_m is modeled as the **product** of their individual **intensities** [1, 30, 31]: I(p_m, t) = I1(p_m, t) I2(p_m).

### 原文上下文

> es [ 26, 29, 42]. In recent years, new eavesdropping modalities based on wireless sensing have been proposed [5, 18, 38, 43, 44]. The core idea is to **use wireless signals**, such as millimeter waves, to sense minute vibrations caused by a speaker and thereby recover the acoustic content. While promising, the effective range of these systems remains very limited—typically only a few meters—making them impractical for stealthy eaves- dropping. Furthermore, **these methods** require the transmission of **dedicated signals** (e.g., **millimeter-wave signals**), which are de- tectable and therefore vulnerable to countermeasures. We propose, for the first time, to employ **moiré patterns** for eaves- dropping. The core idea lies in leveraging the strong amplification capability of **moiré patterns** to amplify tiny vibrations on everyday objects (e.g., a plastic box containing grapes) in our surrounding en- vironment. The underlying principle is that when two gratings with similar spatial frequencies overlap, small relative displacements are SenSys ’26, May 11–14, 2026, Saint Malo, France Zhang et al. Reference Grating Moiré Pattern Photodiode TargetBarcode Audio Source Figure 1: System overview of MoiréEar. optically amplified into a large, moving moiré pattern. Recent work, such as MoiréVib and MoiréPose [30, 31], has showcased the power of moiré amplification for motion sensing. Although prior work has demonstrated the power of moiré amplification, applying it to audio eavesdropping presents ...

### 亮点评价

《MoiréEar: Moiré Can See What You Cannot Hear》（2026）在“Audio Source”中通过 [30] 围绕 optical intensity / product / intensities / moiré patterns / the moiré patterns 展开建模/推导。这说明《MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern》中的相关方法或概念，被后续工作用于理论推导、模型解释或技术论证。

### 评价理由

证据位于“Audio Source”上下文中。原文包含目标引用编号 [30]，可将该段与被引论文建立锚点关系。原文中的关键短语包括：optical intensity / product / intensities / moiré patterns / the moiré patterns。因此判断为理论基础：该段不是单纯列出参考文献，而是在正文技术论述中把目标论文作为建模、推导或概念说明的依据。

### 风险提示

如该段为成组引用，需要人工确认归因范围。

<!-- Citing paper: MoiréEar: Moiré Can See What You Cannot Hear; Evidence quote: the combined optical intensity at position p_m is modeled as the product of their individual intensities [1, 30, 31]: I(p_m, t) = I1(p_m, t) I2(p_m).; Evidence reason: 证据位于“Audio Source”上下文中。原文包含目标引用编号 [30]，可将该段与被引论文建立锚点关系。原文中的关键短语包括：optical intensity / product / intensities / moiré patterns / the moiré patterns。因此判断为理论基础：该段不是单纯列出参考文献，而是在正文技术论述中把目标论文作为建模、推导或概念说明的依据。; card_type: 理论基础; anchor_validation_status: valid_grouped; anchor_validation_reason: citation_text_contains_target_marker -->

### 7. 方法采用：方法采用引用：MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern

**引用论文：** Moiré Vision: A Signal Processing Technology Beyond Pixels Using the Moiré Coordinate  
**发表位置：** unknown, 2023  
**被引用论文：** MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern  
**证据类型：** 方法采用 / 方法采用  
**证据强度：** moderate  
**人工复核建议：** 需要复核  

### 原文证据

> Jingyi et al. **[40]** measure **6-DoF position** with **moiré**.

### 原文上下文

> e markers send both position, ID and small amounts of information simultaneously . This is often used for Augmented Reality [27], [28], [29]. Some tech- niques have been proposed to improve angular accuracy by **showing different patterns** in each angular direction, but it requires a lenticular lens, which limits its usable range [30], [31]. **These processes** generally result in **lower accuracy when using lower-resolution sensors**, **e.g. resulting from the mosaic pattern** of **Bayer coding. Methods** using moir ´ e: Unlike the shadow or projection moir ´e, the sampling moir ´e measures precise surface 2D displacement from a single **image using the digital image sensor** ’s sampling interval as one of **the high-frequency patterns** to generate moir ´e [32]. **Several researchers ex- tended the method** furthermore, as observed in e.g. 3D displacement with multiple cameras [33], [34], in-plane ro- tation angle [35] or in-plane movement (1D-rotation and 2D-translation) [36]. Many researchers use these sampling methods for their applications, such as measuring defor- mation [37], [38] and curved surface residual stress [39]. Although these setups are similar to our methods, they measure displacements or movements instead of position. Thus, their measurable DoF (degree of freedom) is limited. Jingyi et al. **[40]** measure **6-DoF position** with moir ´e. Hou et al. [41] measures lens distortion with moir ´e. However , these methods use dedicated frequency domain or dedicated al- gorithms, which are different ...

### 亮点评价

《Moiré Vision: A Signal Processing Technology Beyond Pixels Using the Moiré Coordinate》（2023）在“Although these setups are similar to our methods, they”中通过 [40] 将《MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern》作为方法来源或方法基础，具体涉及 6-DoF position / moiré / showing different patterns / These processes / lower accuracy when using lower-resolution sensors，说明目标论文的技术路线已进入后续研究的方法链路。

### 评价理由

证据位于“Although these setups are similar to our methods, they”上下文中。原文包含目标引用编号 [40]，可将该段与被引论文建立锚点关系。原文中的关键短语包括：6-DoF position / moiré / showing different patterns / These processes / lower accuracy when using lower-resolution sensors。因此判断为方法采用：该段将目标论文关联到后续方法设计、技术流程或实现依据。

### 风险提示

如该段为成组引用，需要人工确认归因范围。

<!-- Citing paper: Moiré Vision: A Signal Processing Technology Beyond Pixels Using the Moiré Coordinate; Evidence quote: Jingyi et al. [40] measure 6-DoF position with moiré.; Evidence reason: 证据位于“Although these setups are similar to our methods, they”上下文中。原文包含目标引用编号 [40]，可将该段与被引论文建立锚点关系。原文中的关键短语包括：6-DoF position / moiré / showing different patterns / These processes / lower accuracy when using lower-resolution sensors。因此判断为方法采用：该段将目标论文关联到后续方法设计、技术流程或实现依据。; card_type: 方法采用; anchor_validation_status: valid; anchor_validation_reason: citation_text_contains_target_marker -->

### 8. 正向评价：Positive Evaluation: MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern

**引用论文：** MoiréTag: A Low-Cost Tag for High-Precision Tangible Interactions without Active Components  
**发表位置：** Proceedings of the ACM on Human-Computer Interaction, 2024  
**被引用论文：** MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern  
**证据类型：** background / 正向评价  
**证据强度：** moderate  
**人工复核建议：** 需要复核  

### 原文证据

> This Moiré phenomenon has been shown to be **effective** in various applications, such as **pose** **[21]** and camera position [37].

### 原文上下文

> ... d the movement caused by the force interaction [ 23]. However, methods that use laser speckle require a speckle projector and a **speckle sensor** [45] or a defocused camera [23]. In this paper, we present MoiréTag, a novel low-cost tag that enables camera-based sensing of precise movement from physical interactions. It utilizes the Moiré phenomenon, which is **seen when two repetitive patterns** with similar spacings are superim**pose**d in the form of dark and light fringes. If one of **the superimposed patterns** moves, the Moiré fringe will also move, but at a **different rate than the pattern** movement. This allows the small displacement caused by the subtle interaction to be significantly magnified so that it can be easily captured by a regular camera. This Moiré phenomenon has been shown to be **effective** in various applications, such as **pose** **[21]** and camera position [37]. **With the well-established theory framework** of **Moiré pattern** as the basis, MoiréTag provides an easy way for people to use the Moiré phenomenon to create and use ad-hoc interfaces. MoiréTag consists of two overlapping paper layers that have stripe patterns with different grating periods that create Moiré fringes that serve as a displacement magnifier for a camera to precisely capture the displacement. We implemented an image processing pipeline that recognizes the M

### 亮点评价

《MoiréTag: A Low-Cost Tag for High-Precision Tangible Interactions without Active Components》（Proceedings of the ACM on Human-Computer Interaction / 2024）在“On the other hand, recent advancements in computer vision and machine learning algorithms”中通过 [21] 对《MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern》给出明确正向评价，其依据来自 section=On the other hand, recent advancements in computer vision and machine learning algorithms; marker=[21]; terms=pose, effective, the superimposed patterns, different rate than the pattern, Moiré pattern，可作为亮点评价候选。

### 评价理由

证据位于“On the other hand, recent advancements in computer vision and machine learning algorithms”上下文中。原文包含目标引用编号 [21]，可将该段与被引论文建立锚点关系。原文中的关键短语包括：pose / effective / the superimposed patterns / different rate than the pattern / Moiré pattern。因此判断为正向证据：该段包含可追溯到原文的正向评价或使用依据。

### 风险提示

如该段为成组引用，需要人工确认归因范围。

<!-- Citing paper: MoiréTag: A Low-Cost Tag for High-Precision Tangible Interactions without Active Components; Evidence quote: This Moiré phenomenon has been shown to be effective in various applications, such as pose [21] and camera position [37].; Evidence reason: 证据位于“On the other hand, recent advancements in computer vision and machine learning algorithms”上下文中。原文包含目标引用编号 [21]，可将该段与被引论文建立锚点关系。原文中的关键短语包括：pose / effective / the superimposed patterns / different rate than the pattern / Moiré pattern。因此判断为正向证据：该段包含可追溯到原文的正向评价或使用依据。; card_type: 正向评价; anchor_validation_status: valid_grouped; anchor_validation_reason: citation_text_contains_target_marker -->

### 9. 代表性相关工作：代表性相关工作：MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern

**引用论文：** MoiréTag: A Low-Cost Tag for High-Precision Tangible Interactions without Active Components  
**发表位置：** Proceedings of the ACM on Human-Computer Interaction, 2024  
**被引用论文：** MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern  
**证据类型：** 代表性相关工作 / 代表性相关工作  
**证据强度：** moderate  
**人工复核建议：** 需要复核  

### 原文证据

> While there have been several attempts to **use Moiré patterns** **for sensing and tracking** objects **[21]**, visualizing interactions [31], and analyzing mechanical properties [4], little has been studied about the use of **Moiré patterns** for indirectly **sensing** human interactions.

### 原文上下文

> movement, making it more suitable for **sensing** large-scale movements such as moving an arm or a hand. However, in the real world, people also utilize small movements, such as precisely aligning objects, and even tiny actions that may not be easily noticeable, such as applying a force on a physical object. Other studies have shown that using laser speckles can enable high-accuracy **sensing** of small movements, such as the movement of hand and object [ 45] and the movement caused by the force interaction [ 23]. However, methods that use laser speckle require a speckle projector and a **speckle sensor** [45] or a defocused camera [23]. In this paper, we present MoiréTag, a novel low-cost tag that enables camera-based **sensing** of precise movement from physical interactions. It utilizes the Moiré phenomenon, which is **seen when two repetitive patterns** with similar spacings are superimposed in the form of dark and light fringes. If one of **the superimposed patterns** moves, the Moiré fringe will also move, but at a **different rate than the pattern** movement. This allows the small displacement caused by the subtle interaction to be significantly magnified so that it can be easily captured by a regular camera. This Moiré phenomenon has been shown to be effective in various applications, such as pose **[21]** and camera position [37]. With the well-established theory framework of **Moiré pattern** as the basis, MoiréTag provides an easy way for people to use the Moiré phenomenon to create and use ad-hoc ...

### 亮点评价

《MoiréTag: A Low-Cost Tag for High-Precision Tangible Interactions without Active Components》（Proceedings of the ACM on Human-Computer Interaction / 2024）在“On the other hand, recent advancements in computer vision and machine learning algorithms”中将《MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern》纳入后续技术路线梳理，并提到 sensing / tracking / use Moiré patterns / for sensing and tracking / Moiré patterns。这说明目标论文已进入该方向的技术脉络，但原文没有给出直接性能评价或高度赞扬。 该证据宜表述为相关工作引用或技术脉络引用，不宜表述为直接正向赞扬。 风险提示：这不是直接正向评价，不应包装成直接正向赞扬。

### 评价理由

证据位于“On the other hand, recent advancements in computer vision and machine learning algorithms”上下文中。原文包含目标引用编号 [21]，可将该段与被引论文建立锚点关系。原文中的关键短语包括：sensing / tracking / use Moiré patterns / for sensing and tracking / Moiré patterns。因此判断为代表性相关工作：该段体现目标论文被纳入相关工作或技术路线梳理，但不是直接直接正向赞扬。

### 风险提示

这不是直接正向评价，不应包装成直接正向赞扬。

<!-- Citing paper: MoiréTag: A Low-Cost Tag for High-Precision Tangible Interactions without Active Components; Evidence quote: While there have been several attempts to use Moiré patterns for sensing and tracking objects [21], visualizing interactions [31], and analyzing mechanical properties [4], little has been studied about the use of Moiré patterns for indirectly sensing human interactions.; Evidence reason: 证据位于“On the other hand, recent advancements in computer vision and machine learning algorithms”上下文中。原文包含目标引用编号 [21]，可将该段与被引论文建立锚点关系。原文中的关键短语包括：sensing / tracking / use Moiré patterns / for sensing and tracking / Moiré patterns。因此判断为代表性相关工作：该段体现目标论文被纳入相关工作或技术路线梳理，但不是直接直接正向赞扬。; card_type: 代表性相关工作; anchor_validation_status: valid_grouped; anchor_validation_reason: citation_text_contains_target_marker -->

## 三、代表性相关工作 / 普通引用

### 11. 代表性相关工作：代表性相关工作：MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern

**引用论文：** MoiréLens: Bringing Schlieren Imaging into Real-World Environments Using Moiré Patterns  
**发表位置：** unknown, 2026  
**被引用论文：** MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern  
**证据类型：** 代表性相关工作 / 代表性相关工作  
**证据强度：** weak  
**人工复核建议：** 需要复核  

### 原文证据

> Interference between a camera CFA and a high-frequency **grid background enables ultra-precise pose estimation** **and tracking** [19–21]. **MoiréPose** targets **6-DoF localization** **[19]**, and MoiréVision extends this concept to **curvilinear patterns with sub-pixel feature** extraction [20]. MoiréVib demodulates periodic fringe motion for micro-vibration sensing [21].

### 原文上下文

> butions in this work: •We present MoiréLens, a Moiré-based Schlieren imaging frame- work that replaces traditional optical assemblies with high- frequency fringe backgrounds and commodity cameras, enabling low-cost, high-sensitivity, extended-range, and robust Schlieren imaging in real-world environments. 1275 MoiréLens: Bringing Schlieren Imaging **into Real-World Environments Using Moiré Patterns** SenSys ’26, May 11–14, 2026, Saint Malo, France •We develop AutoMoiré, an automatic calibration and control module that continuously maintains geometric alignment and stable Moiré formation under varying camera viewpoints. •We design a human-invisible background embedding **and adap- tive Moiré-to-Schlieren conversion pipeline** that integrates near- invisible fringes into wallpapers and extracts Moiré distortions with tunable spatial–temporal sensitivity. •We demonstrate that MoiréLens effectively reconstructs thermal and gaseous flows using only commodity cameras and lightweight image processing, supporting diverse real-world applications such as gas-leak localization, HVAC monitoring and cooking automation. 2 **Related Work Sensing Using Moiré Patterns** : Moiré patterns have been used in visual sensing because small geometric displacements yield large, measurable phase shifts in the fringes [5, 19–22, 33, 36, 37]. Existing designs typically generate Moiré patterns in two ways: (i) Tag-based (stacked gratings). Two high-frequency gratings are rigidly stacked on a passive marker to ...

### 亮点评价

《MoiréLens: Bringing Schlieren Imaging into Real-World Environments Using Moiré Patterns》（2026）在 Related Work 中将《MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern》纳入后续技术路线梳理，并提到 MoiréPose / ultra-precise / 6-DoF localization / grid background enables ultra-precise pose estimation / and tracking。这说明目标论文已进入该方向的技术脉络，但原文没有给出直接性能评价或高度赞扬。 原文中可直接核验的相关表述包括“vibration sensing / micro-vibration”。 该证据宜表述为相关工作引用或技术脉络引用，不宜表述为直接正向赞扬。 风险提示：这不是直接正向评价，不应包装成直接正向赞扬。

### 评价理由

证据位于“2 Related Work”上下文中。原文包含目标引用编号 [19]，可将该段与被引论文建立锚点关系。原文中的关键短语包括：MoiréPose / ultra-precise / 6-DoF localization / grid background enables ultra-precise pose estimation / and tracking。因此判断为代表性相关工作：该段体现目标论文被纳入相关工作或技术路线梳理，但不是直接直接正向赞扬。若用于精度/传感能力佐证，原文明确出现：vibration sensing / micro-vibration。

### 风险提示

这不是直接正向评价，不应包装成直接正向赞扬。

<!-- Citing paper: MoiréLens: Bringing Schlieren Imaging into Real-World Environments Using Moiré Patterns; Evidence quote: Interference between a camera CFA and a high-frequency grid background enables ultra-precise pose estimation and tracking [19–21]. MoiréPose targets 6-DoF localization [19], and MoiréVision extends this concept to curvilinear patterns with sub-pixel feature extraction [20]. MoiréVib demodulates periodic fringe motion for micro-vibration sensing [21].; Evidence reason: 证据位于“2 Related Work”上下文中。原文包含目标引用编号 [19]，可将该段与被引论文建立锚点关系。原文中的关键短语包括：MoiréPose / ultra-precise / 6-DoF localization / grid background enables ultra-precise pose estimation / and tracking。因此判断为代表性相关工作：该段体现目标论文被纳入相关工作或技术路线梳理，但不是直接直接正向赞扬。若用于精度/传感能力佐证，原文明确出现：vibration sensing / micro-vibration。; card_type: 代表性相关工作; anchor_validation_status: valid_grouped; anchor_validation_reason: citation_text_contains_target_marker -->

### 12. 代表性相关工作：代表性相关工作：MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern

**引用论文：** MoiréLens: Bringing Schlieren Imaging into Real-World Environments Using Moiré Patterns  
**发表位置：** unknown, 2026  
**被引用论文：** MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern  
**证据类型：** 代表性相关工作 / 代表性相关工作  
**证据强度：** weak  
**人工复核建议：** 需要复核  

### 原文证据

> **Moiré patterns** have been used in **visual sensing** because small geometric displacements yield large, measurable **phase shifts** in the fringes [5, 19–22, 33, 36, 37].

### 原文上下文

> ... May 11–14, 2026, Saint Malo, France •We develop AutoMoiré, an automatic calibration and control module that continuously maintains geometric alignment and stable Moiré formation under varying camera viewpoints. •We design a human-invisible background embedding **and adap- tive Moiré-to-Schlieren conversion pipeline** that integrates near- invisible fringes into wallpapers and extracts Moiré distortions with tunable spatial–temporal sensitivity. •We demonstrate that MoiréLens effectively reconstructs thermal and gaseous flows using only commodity cameras and lightweight image processing, supporting diverse real-world applications such as gas-leak localization, HVAC monitoring and cooking automation. 2 **Related Work Sensing Using Moiré Patterns** : **Moiré patterns** have been used in **visual sensing** because small geometric displacements yield large, measurable **phase shifts** in the fringes [5, 19–22, 33, 36, 37]. **Existing designs typically generate Moiré patterns** in two ways: (i) Tag-based (stacked gratings). Two high-frequency gratings are rigidly stacked on a passive marker to produce stable, high-SNR interference: MoiréBoard enables low-cost, **calibration-light 3-DoF tracking** [33]; MoiréTag supports angular/6D **snapshot tracking via chirped patterns** [22, 37]; MoiréWidgets provide interactive controls such as buttons, sliders, and dials [ 5]. Because both gratings are rigidly bond

### 亮点评价

《MoiréLens: Bringing Schlieren Imaging into Real-World Environments Using Moiré Patterns》（2026）在 Related Work 中将《MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern》纳入后续技术路线梳理，并提到 Moiré patterns / visual sensing / phase shifts / lieren conversion pipeline / into Real-World Environments Using Moiré Patterns。这说明目标论文已进入该方向的技术脉络，但原文没有给出直接性能评价或高度赞扬。 该证据宜表述为相关工作引用或技术脉络引用，不宜表述为直接正向赞扬。 风险提示：这不是直接正向评价，不应包装成直接正向赞扬。

### 评价理由

证据位于“2 Related Work”上下文中。原文包含目标引用编号 [19]，可将该段与被引论文建立锚点关系。原文中的关键短语包括：Moiré patterns / visual sensing / phase shifts / lieren conversion pipeline / into Real-World Environments Using Moiré Patterns。因此判断为代表性相关工作：该段体现目标论文被纳入相关工作或技术路线梳理，但不是直接直接正向赞扬。

### 风险提示

这不是直接正向评价，不应包装成直接正向赞扬。

<!-- Citing paper: MoiréLens: Bringing Schlieren Imaging into Real-World Environments Using Moiré Patterns; Evidence quote: Moiré patterns have been used in visual sensing because small geometric displacements yield large, measurable phase shifts in the fringes [5, 19–22, 33, 36, 37].; Evidence reason: 证据位于“2 Related Work”上下文中。原文包含目标引用编号 [19]，可将该段与被引论文建立锚点关系。原文中的关键短语包括：Moiré patterns / visual sensing / phase shifts / lieren conversion pipeline / into Real-World Environments Using Moiré Patterns。因此判断为代表性相关工作：该段体现目标论文被纳入相关工作或技术路线梳理，但不是直接直接正向赞扬。; card_type: 代表性相关工作; anchor_validation_status: valid_grouped; anchor_validation_reason: citation_text_contains_target_marker -->

### 13. 代表性相关工作：代表性相关工作：MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern

**引用论文：** MoiréEar: Moiré Can See What You Cannot Hear  
**发表位置：** unknown, 2026  
**被引用论文：** MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern  
**证据类型：** 代表性相关工作 / 代表性相关工作  
**证据强度：** weak  
**人工复核建议：** 需要复核  

### 原文证据

> Building on this idea, Ning et al. **[30]** introduced **MoiréPose**, extending the approach to **6-DoF pose estimation** in camera-to-screen interaction scenarios.

### 原文上下文

> es [ 26, 29, 42]. In recent years, new eavesdropping modalities based on wireless sensing have been proposed [5, 18, 38, 43, 44]. The core idea is to **use wireless signals**, such as millimeter waves, to sense minute vibrations caused by a speaker and thereby recover the acoustic content. While promising, the effective range of these systems remains very limited—typically only a few meters—making them impractical for stealthy eaves- dropping. Furthermore, **these methods** require the transmission of **dedicated signals** (e.g., **millimeter-wave signals**), which are de- tectable and therefore vulnerable to countermeasures. We propose, for the first time, to **employ moiré patterns** for eaves- dropping. The core idea lies in leveraging the strong amplification capability of **moiré patterns** to amplify tiny vibrations on everyday objects (e.g., a plastic box containing grapes) in our surrounding en- vironment. The underlying principle is that when two gratings with similar spatial frequencies overlap, small relative displacements are SenSys ’26, May 11–14, 2026, Saint Malo, France Zhang et **al. Reference Grating Moiré Pattern** Photodiode TargetBarcode Audio Source Figure 1: System overview of MoiréEar. optically amplified into a large, moving moiré pattern. Recent work, such as MoiréVib and **MoiréPose** [30, 31], has showcased the power of moiré amplification for motion sensing. Although prior work has demonstrated the power of moiré amplification, applying it to audio eavesdropping presents ...

### 亮点评价

《MoiréEar: Moiré Can See What You Cannot Hear》（2026）在“Audio Source”中将《MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern》纳入后续技术路线梳理，并提到 MoiréPose / 6-DoF pose estimation / moiré patterns / the moiré patterns / use wireless signals。这说明目标论文已进入该方向的技术脉络，但原文没有给出直接性能评价或高度赞扬。 该证据宜表述为相关工作引用或技术脉络引用，不宜表述为直接正向赞扬。 风险提示：这不是直接正向评价，不应包装成直接正向赞扬。

### 评价理由

证据位于“Audio Source”上下文中。原文包含目标引用编号 [30]，可将该段与被引论文建立锚点关系。原文中的关键短语包括：MoiréPose / 6-DoF pose estimation / moiré patterns / the moiré patterns / use wireless signals。因此判断为代表性相关工作：该段体现目标论文被纳入相关工作或技术路线梳理，但不是直接直接正向赞扬。

### 风险提示

这不是直接正向评价，不应包装成直接正向赞扬。

<!-- Citing paper: MoiréEar: Moiré Can See What You Cannot Hear; Evidence quote: Building on this idea, Ning et al. [30] introduced MoiréPose, extending the approach to 6-DoF pose estimation in camera-to-screen interaction scenarios.; Evidence reason: 证据位于“Audio Source”上下文中。原文包含目标引用编号 [30]，可将该段与被引论文建立锚点关系。原文中的关键短语包括：MoiréPose / 6-DoF pose estimation / moiré patterns / the moiré patterns / use wireless signals。因此判断为代表性相关工作：该段体现目标论文被纳入相关工作或技术路线梳理，但不是直接直接正向赞扬。; card_type: 代表性相关工作; anchor_validation_status: valid; anchor_validation_reason: citation_text_contains_target_marker -->

### 14. 代表性相关工作：代表性相关工作：MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern

**引用论文：** Visual-Based Out-of-Plane Rotation Measurement Using 3-D Moiré-Based Marker  
**发表位置：** IEEE Transactions on Instrumentation and Measurement, 2025  
**被引用论文：** MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern  
**证据类型：** 代表性相关工作 / 代表性相关工作  
**证据强度：** weak  
**人工复核建议：** 需要复核  

### 原文证据

> **Some methods** leverage the **aliasing effect** **[15]**, [16], [17], which arises when a camera captures a target with a **periodic pattern** whose frequency closely matches the camera's **color filter array. The aliasing pattern** is sensitive to the pose of the target, introducing the potential of an **ultraprecise out-of-plane rotation measurement**. However, the **reported accuracy does not demonstrate superiority** when compared to traditional solutions, which might be due to the inherently low-quality imaging of **aliasing patterns**.

### 原文上下文

> t **mainly includes feature-based methods** [8] **and deep learning-based methods** [11]. The out-of-plane rotation measurement is more challenging than the in-plane one because the images of the target before and after rotation have a signiﬁcantly smaller di ﬀerence (see the top-right of each picture in Fig. 1). Traditional methods use the perspective-from-n-points (PnP) [12] or correlation- based [13] algorithms, which determine the angle based on several visual features on the target. However, compared to in-plane rotation, these features barely move in the image as they primarily change in depth, thus the accuracy is unsatisfactory. There are more e ﬀective methods for out-of-plane rotation measurement, **which usually involve new imaging models**. For instance, Gu et al. [14] designed a meta-surface composed of an array of blocks, each exhibiting a unique reﬂective property. Under illumination, the meta-surface has a shim- mering grayscale variation, which is sensitive to out-of-plane rotation. Some drawbacks hinder the practicality of this method. First, the meta-surface is di ﬃcult to manufacture. Second, its deployment is complicated by the need for a controlled light source, speciﬁc measurement conditions, and a complex calibration process. **Some methods** leverage the aliasing e ﬀect **[15]**, [16], [17], which arises when a camera 1557-9662 © 2025 IEEE. All rights reserved, including rights for text and data mining, and training of artiﬁcial intelligence and similar technologies. ...

### 亮点评价

《Visual-Based Out-of-Plane Rotation Measurement Using 3-D Moiré-Based Marker》（IEEE Transactions on Instrumentation and Measurement / 2025）在“Second, its deployment is complicated by the need for a”中将《MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern》纳入后续技术路线梳理，并提到 aliasing effect / ultraprecise out-of-plane rotation measurement / reported accuracy does not demonstrate superiority / Some methods / periodic pattern。这说明目标论文已进入该方向的技术脉络，但原文没有给出直接性能评价或高度赞扬。 该证据宜表述为相关工作引用或技术脉络引用，不宜表述为直接正向赞扬。 风险提示：这是成组引用，需要人工确认归因范围。 这不是直接正向评价，不应包装成直接正向赞扬。

### 评价理由

证据位于“Second, its deployment is complicated by the need for a”上下文中。原文包含目标引用编号 [15]，可将该段与被引论文建立锚点关系。原文中的关键短语包括：aliasing effect / ultraprecise out-of-plane rotation measurement / reported accuracy does not demonstrate superiority / Some methods / periodic pattern。因此判断为代表性相关工作：该段体现目标论文被纳入相关工作或技术路线梳理，但不是直接直接正向赞扬。该证据来自成组引用，不能自动断言所有评价均唯一归属于目标论文。

### 风险提示

这是成组引用，需要人工确认归因范围。 这不是直接正向评价，不应包装成直接正向赞扬。

<!-- Citing paper: Visual-Based Out-of-Plane Rotation Measurement Using 3-D Moiré-Based Marker; Evidence quote: Some methods leverage the aliasing effect [15], [16], [17], which arises when a camera captures a target with a periodic pattern whose frequency closely matches the camera's color filter array. The aliasing pattern is sensitive to the pose of the target, introducing the potential of an ultraprecise out-of-plane rotation measurement. However, the reported accuracy does not demonstrate superiority when compared to traditional solutions, which might be due to the inherently low-quality imaging of aliasing patterns.; Evidence reason: 证据位于“Second, its deployment is complicated by the need for a”上下文中。原文包含目标引用编号 [15]，可将该段与被引论文建立锚点关系。原文中的关键短语包括：aliasing effect / ultraprecise out-of-plane rotation measurement / reported accuracy does not demonstrate superiority / Some methods / periodic pattern。因此判断为代表性相关工作：该段体现目标论文被纳入相关工作或技术路线梳理，但不是直接直接正向赞扬。该证据来自成组引用，不能自动断言所有评价均唯一归属于目标论文。; card_type: 代表性相关工作; anchor_validation_status: valid_grouped; anchor_validation_reason: citation_text_contains_target_marker -->

### 15. 代表性相关工作：代表性相关工作：MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern

**引用论文：** UbiPose: Towards Ubiquitous Outdoor AR Pose Tracking using Aerial Meshes  
**发表位置：** MobiCom, 2023  
**被引用论文：** MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern  
**证据类型：** 代表性相关工作 / 代表性相关工作  
**证据强度：** weak  
**人工复核建议：** 需要复核  
**重要作者：** Ramesh Govindan（ACM Fellow）  

### 原文证据

> Other work **explores estimating pose leveraging moir’e patterns**’ high sensitivity to **the camera’s pose changes** **[60]**, **and improving pose tracking** **using inertial sensors** [2, 75, 91].

### 原文上下文

> ew synthesis to generate reference poses for a given query image, but this takes 10-20 s per frame. MeshLoc [ 67] **uses terrestrial meshes for neural feature** extraction and matching. UbiPose obtains high pose accuracy in areas where terrestrial meshes may not be available and can run fast on mobile devices. SLAM based visual localization.SLAM [28] simultane- ously estimates pose and builds a 3D map of an environment. Visual SLAM [19], like SfM, builds sparse 3D feature maps of the environment. If these maps were widely available, they **could potentially enable ubiquitous pose tracking**, but would have the same drawback as terrestrial imagery: at scale, they could only be collected using vehicles [ 1]. UbiPose, using aerial meshes, enables wider coverage for AR pose tracking. Other camera pose estimation **and tracking** approaches. PoseNet [46] is a CNN-based 6-DoF pose estimator. A line of work has improved upon PoseNet using various tech- niques [ 16, 27, 57, 78, 79, 86–88]. Even though these tech- **niques can estimate absolute pose estimation** quickly, their accuracy is worse than approaches, like UbiPose, that ex- ploit imagery or dense structural models of the environment. Other work explores estimating pose leveraging moir’e pat- terns’ high sensitivity to **the camera’s pose changes** **[60]**, **and improving pose tracking** **using inertial sensors** [2, 75, 91]. 7 CONCLUSIONS UbiPose extends coverage of AR pose tracking on mobile devices to areas where terrestrial imagery is not available. ...

### 亮点评价

Ramesh Govindan（ACM Fellow）团队在《UbiPose: Towards Ubiquitous Outdoor AR Pose Tracking using Aerial Meshes》（MobiCom / 2023）在 Related Work 中将《MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern》纳入后续技术路线梳理，并提到 moir’e patterns / pose changes / explores estimating pose leveraging moir’e patterns / the camera’s pose changes / and improving pose tracking。这说明目标论文已进入该方向的技术脉络，但原文没有给出直接性能评价或高度赞扬。 该证据宜表述为相关工作引用或技术脉络引用，不宜表述为直接正向赞扬。 风险提示：这是成组引用，需要人工确认归因范围。 这不是直接正向评价，不应包装成直接正向赞扬。

### 评价理由

证据位于“6 RELATED WORK”上下文中。原文包含目标引用编号 [60]，可将该段与被引论文建立锚点关系。原文中的关键短语包括：moir’e patterns / pose changes / explores estimating pose leveraging moir’e patterns / the camera’s pose changes / and improving pose tracking。因此判断为代表性相关工作：该段体现目标论文被纳入相关工作或技术路线梳理，但不是直接直接正向赞扬。该证据来自成组引用，不能自动断言所有评价均唯一归属于目标论文。

### 风险提示

这是成组引用，需要人工确认归因范围。 这不是直接正向评价，不应包装成直接正向赞扬。

<!-- Citing paper: UbiPose: Towards Ubiquitous Outdoor AR Pose Tracking using Aerial Meshes; Evidence quote: Other work explores estimating pose leveraging moir’e patterns’ high sensitivity to the camera’s pose changes [60], and improving pose tracking using inertial sensors [2, 75, 91].; Evidence reason: 证据位于“6 RELATED WORK”上下文中。原文包含目标引用编号 [60]，可将该段与被引论文建立锚点关系。原文中的关键短语包括：moir’e patterns / pose changes / explores estimating pose leveraging moir’e patterns / the camera’s pose changes / and improving pose tracking。因此判断为代表性相关工作：该段体现目标论文被纳入相关工作或技术路线梳理，但不是直接直接正向赞扬。该证据来自成组引用，不能自动断言所有评价均唯一归属于目标论文。; card_type: 代表性相关工作; anchor_validation_status: valid_grouped; anchor_validation_reason: citation_text_contains_target_marker -->

### 16. 代表性相关工作：代表性相关工作：MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern

**引用论文：** MoiréEar: Moiré Can See What You Cannot Hear  
**发表位置：** unknown, 2026  
**被引用论文：** MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern  
**证据类型：** 代表性相关工作 / 代表性相关工作  
**证据强度：** weak  
**人工复核建议：** 需要复核  

### 原文证据

> Recent work, such as MoiréVib and **MoiréPose** [30, 31], has showcased the power of **moiré amplification** for **motion sensing**.

### 原文上下文

> ... ed signals (e.g., **millimeter-wave signals**), which are de- tectable and therefore vulnerable to countermeasures. We propose, for the first time, to employ **moiré patterns** for eaves- dropping. The core idea lies in leveraging the strong amplification capability of **moiré patterns** to amplify tiny vibrations on everyday objects (e.g., a plastic box containing grapes) in our surrounding en- vironment. The underlying principle is that when two gratings with similar spatial frequencies overlap, small relative displacements are SenSys ’26, May 11–14, 2026, Saint Malo, France Zhang et al. Reference Grating Moiré Pattern Photodiode TargetBarcode Audio Source Figure 1: System overview of MoiréEar. optically amplified into a large, moving moiré pattern. Recent work, such as MoiréVib and **MoiréPose** [30, 31], has showcased the power of **moiré amplification** for **motion sensing**. Although prior work has demonstrated the power of **moiré amplification**, applying it to audio eavesdropping presents fundamentally different challenges. •Challenge 1: Previous measurement-oriented applications rely on well-designed, dedicated moiré gratings. However, achieving practical and stealthy eavesdropping requires leveraging every- day objects. For instance, instead of relying on specially designed moiré gratings,

### 亮点评价

《MoiréEar: Moiré Can See What You Cannot Hear》（2026）在“Audio Source”中将《MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern》纳入后续技术路线梳理，并提到 MoiréPose / moiré amplification / motion sensing / moiré patterns / the moiré patterns。这说明目标论文已进入该方向的技术脉络，但原文没有给出直接性能评价或高度赞扬。 该证据宜表述为相关工作引用或技术脉络引用，不宜表述为直接正向赞扬。 风险提示：这是成组引用，需要人工确认归因范围。 这不是直接正向评价，不应包装成直接正向赞扬。

### 评价理由

证据位于“Audio Source”上下文中。原文包含目标引用编号 [30]，可将该段与被引论文建立锚点关系。原文中的关键短语包括：MoiréPose / moiré amplification / motion sensing / moiré patterns / the moiré patterns。因此判断为代表性相关工作：该段体现目标论文被纳入相关工作或技术路线梳理，但不是直接直接正向赞扬。该证据来自成组引用，不能自动断言所有评价均唯一归属于目标论文。

### 风险提示

这是成组引用，需要人工确认归因范围。 这不是直接正向评价，不应包装成直接正向赞扬。

<!-- Citing paper: MoiréEar: Moiré Can See What You Cannot Hear; Evidence quote: Recent work, such as MoiréVib and MoiréPose [30, 31], has showcased the power of moiré amplification for motion sensing.; Evidence reason: 证据位于“Audio Source”上下文中。原文包含目标引用编号 [30]，可将该段与被引论文建立锚点关系。原文中的关键短语包括：MoiréPose / moiré amplification / motion sensing / moiré patterns / the moiré patterns。因此判断为代表性相关工作：该段体现目标论文被纳入相关工作或技术路线梳理，但不是直接直接正向赞扬。该证据来自成组引用，不能自动断言所有评价均唯一归属于目标论文。; card_type: 代表性相关工作; anchor_validation_status: valid_grouped; anchor_validation_reason: citation_text_contains_target_marker -->

## 四、需要人工复核的候选

暂无。

## 五、已排除误报摘要

citation_text_contains_target_marker: 9；no_target_reference_marker_available: 1；target_anchor_missing: 1
