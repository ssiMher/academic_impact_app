# 亮点引用证据报告

## 一、报告摘要

- 学者会话：Lei Xie 0004
- 推荐纳入证据数：4
- 候选复核证据数：45
- 局限性/不宜作为亮点证据数：12
- 不纳入证据数：196

## 结论摘要

- 是否发现第三方明确亚毫米级佐证：发现直接亚毫米级强候选文本证据，例如 “Its applications range from measuring environmental parameters like temperature [2] and humidity[3], to detecting sub-millimeter-level vibrations [4]”，但引用编号或参考文献条目仍需人工核验。
- 是否发现 first / pioneering 评价：目前未发现可靠第三方明确将 first / pioneering 作用到目标论文。
- 是否发现能力认可：发现 4 条能力认可证据，主要涉及 RFID through-wall eavesdropping、speaker/loudspeaker vibration sensing 或明确方法/性能使用。
- 不宜过度解读：普通相关工作、成组引用、标题-only、reference-only、局限性反馈不能作为正向亮点；本次另有 7 条直接亚毫米候选、38 条候选复核、12 条局限性/不宜作为亮点、196 条不纳入。

## 二、推荐纳入

暂无。

### 直接亚毫米级佐证

暂无。

### 能力认可佐证

### 1. 穿墙窃听能力佐证

**引用论文：** Rf sensing security and malicious exploitation: A comprehensive survey  
**被引用论文：** Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration  
**建议：** 推荐纳入  
**置信度：** high  

#### 原文证据

> Similarly, Wang et al. **[102]** proposed Tag-Bug, a **through-wall eavesdropping** system based on **RFID tags** that **reconstructs audio** by capturing **vibrations from loudspeakers**.

#### 对应参考文献（引用论文原文 References 中的条目）

> **[102]** C. Wang, L. Xie, Y . Lin, W. Wang, Y . Chen, Y . Bu, K. Zhang,
> and S. Lu, “Thru-the-wall eavesdropping on loudspeakers via RFID
> by capturing **sub-mm level vibration**,” Proceedings of the ACM on
> Interactive, Mobile, Wearable and Ubiquitous Technologies , vol. 5,
> no. 4, pp. 1–25, 2021.

#### 原文上下文

> Similarly, Wang et al. **[102]** proposed Tag-Bug, a **through-wall eavesdropping** system based on **RFID tags** that **reconstructs audio** by capturing **vibrations from loudspeakers**. This approach attaches **RFID tags** to various everyday objects

#### 亮点评价

该综述指出 Tag-Bug [102] 是一个基于 RFID 的穿墙窃听系统，通过捕获扬声器振动来重建音频。

#### 评价理由

正文明确提到 [102] 提出了基于 RFID 的穿墙窃听系统 Tag-Bug，通过捕获扬声器振动重建音频，直接对应 through-wall eavesdropping 和 RFID loudspeaker vibration capability。

### 2. performance_comparison

**引用论文：** Rf sensing security and malicious exploitation: A comprehensive survey  
**被引用论文：** Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration  
**建议：** 推荐纳入  
**置信度：** high  

#### 原文证据

> Tag-Bug **[102]** 2021 Loudspeaker 920MHz & 2.4GHz (RFID&USRP N210) 4m ✓ H # CA 2kHz Word Recognition

#### 对应参考文献（引用论文原文 References 中的条目）

> **[102]** C. Wang, L. Xie, Y . Lin, W. Wang, Y . Chen, Y . Bu, K. Zhang,
> and S. Lu, “Thru-the-wall eavesdropping on loudspeakers via RFID
> by capturing **sub-mm level vibration**,” Proceedings of the ACM on
> Interactive, Mobile, Wearable and Ubiquitous Technologies , vol. 5,
> no. 4, pp. 1–25, 2021.

#### 原文上下文

> TABLE VIII COMPARISON OF ACOUSTIC EAVESDROPPING VIA RF SIGNALS ... Tag-Bug **[102]** 2021 Loudspeaker 920MHz & 2.4GHz (RFID&USRP N210) 4m ✓ H # CA 2kHz Word Recognition

#### 亮点评价

该综述在 acoustic eavesdropping 方案对比表中列出了 Tag-Bug [102] 的关键性能参数，包括工作频率、最大距离、穿墙能力等。

#### 评价理由

表格对比中明确列出 Tag-Bug [102] 的各项性能参数（音频源、信号类型、距离、穿墙能力、训练需求、指标、采样率、窃听类型），属于 concrete performance comparison。

### 3. 穿墙窃听能力佐证

**引用论文：** RF-AbVib: Environment-independent vibration monitoring using COTS RFID devices  
**被引用论文：** Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration  
**建议：** 推荐纳入  
**置信度：** high  

#### 原文证据

> Wang et al. **[23]** extended RFID sensing to enable **through-wall eavesdropping**.

#### 对应参考文献（引用论文原文 References 中的条目）

> **[23]** C. Wang, L. Xie, Y. Lin, W. Wang, Y. Chen, Y. Bu, K. Zhang, S. Lu, Thru-the-wall 
> eavesdropping on loudspeakers via RFID by capturing **sub-mm level vibration**, Proc. 
> ACM Interact., Mob., Wearable Ubiquitous Technol. 5 (4) (2021) 1–25.

#### 原文上下文

> TagMic [22], built with COTS devices, was the first to show **RFID tags** could be used for eavesdropping. Wang et al. **[23]** extended RFID sensing to enable **through-wall eavesdropping**. RF-Mic [20] uses **RFID tags** to create a low-cost, hidden, and flexible voice monitoring system, marking an early application of RFID in voice surveillance.

#### 亮点评价

引用论文在相关工作第6.1.3节中确认，目标论文[23]（Wang等人）将RFID感知扩展到实现穿墙窃听。

#### 评价理由

引用论文正文明确说明目标论文[23]实现了穿墙窃听，直接对应claim_type中的through_wall_eavesdropping能力。原文使用'extended RFID sensing to enable through-wall eavesdropping'，明确锚定目标论文。

### 4. 穿墙窃听能力佐证

**引用论文：** Rf sensing security and malicious exploitation: A comprehensive survey  
**被引用论文：** Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration  
**建议：** 推荐纳入  
**置信度：** high  

#### 原文证据

> Wang et al. **[102]** proposed Tag-Bug, a **through-wall eavesdropping** system based on **RFID tags** that **reconstructs audio** by capturing **vibrations from loudspeakers**.

#### 对应参考文献（引用论文原文 References 中的条目）

> **[102]** C. Wang, L. Xie, Y . Lin, W. Wang, Y . Chen, Y . Bu, K. Zhang,
> and S. Lu, “Thru-the-wall eavesdropping on loudspeakers via RFID
> by capturing **sub-mm level vibration**,” Proceedings of the ACM on
> Interactive, Mobile, Wearable and Ubiquitous Technologies , vol. 5,
> no. 4, pp. 1–25, 2021.

#### 原文上下文

> Shifting the focus of attacks to eavesdropping on audio emitted by loudspeakers, UWHear [101] proposed using sub-10 GHz band IR-UWB radar for non-contact acoustic eavesdropping. ... Similarly, Wang et al. **[102]** proposed Tag-Bug, a **through-wall eavesdropping** system based on **RFID tags** that **reconstructs audio** by capturing **vibrations from loudspeakers**.

#### 亮点评价

引用论文明确指出目标论文（Tag-Bug）是一个基于RFID标签的穿墙窃听系统，通过捕获扬声器振动来重建音频。

#### 评价理由

正文直接使用了[102]作为标记，明确说明目标论文是穿墙窃听系统，基于RFID标签并通过捕获扬声器振动重建音频，符合穿墙窃听能力识别。

## 三、直接亚毫米级佐证候选：需人工核对引用编号

### 5. 直接亚毫米精度佐证

**引用论文：** Detection and Recovery of RFID Harmonic Signal for Wi-Fi Interference  
**被引用论文：** Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration  
**建议：** 候选复核  
**置信度：** high  

#### 原文证据

> Its applications range from measuring environmental parameters like temperature [2] and humidity[3], to detecting **sub-millimeter-level vibrations** **[4]**

#### 对应参考文献（引用论文原文 References 中的条目）

> **[4]** W ANG C, XIE L, LIN Y , et al. Thru-the-wall eavesdropping on loud-
> speakers via RFID by capturing **sub-mm level vibration**[J]. Proceed-
> ings of the ACM on Interactive, Mobile, Wearable and Ubiquitous
> Technologies, 2021, 5(4): 1-25.

#### 原文上下文

> Its applications range from measuring environmental parameters like temperature [2] and humidity[3], to detecting **sub-millimeter-level vibrations** **[4]**, and human identification through precise fingerprint recognition [5] and facial identification[6-7].

#### 亮点评价

引用论文将目标论文列为RFID亚毫米级振动检测的普通示例之一，但未展开描述其具体能力。

#### 评价理由

该引用将[4]与[2][3]并列在普通应用列表中，未单独描述目标论文的能力或贡献，属于普通相关工作的列举，不具备高亮点价值。

### 6. 直接亚毫米精度佐证

**引用论文：** Detection and Recovery of RFID Harmonic Signal for Wi-Fi Interference  
**被引用论文：** Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration  
**建议：** 候选复核  
**置信度：** high  

#### 原文证据

> Its applications range from measuring environmental parameters like temperature [2] and humidity[3], to detecting **sub-millimeter-level vibrations** **[4]**, and human identification through precise fingerprint recognition [5] and facial identification[6-7].

#### 对应参考文献（引用论文原文 References 中的条目）

> **[4]** W ANG C, XIE L, LIN Y , et al. Thru-the-wall eavesdropping on loud-
> speakers via RFID by capturing **sub-mm level vibration**[J]. Proceed-
> ings of the ACM on Interactive, Mobile, Wearable and Ubiquitous
> Technologies, 2021, 5(4): 1-25.

#### 原文上下文

> Its applications range from measuring environmental parameters like temperature [2] and humidity[3], to detecting **sub-millimeter-level vibrations** **[4]**, and human identification through precise fingerprint recognition [5] and facial identification[6-7].

#### 亮点评价

目标论文[4]被引用论文作为RFID在亚毫米级振动检测方面的一个应用实例提及。

#### 评价理由

引用论文在列举RFID应用场景时提到了目标论文[4]用于亚毫米级振动检测，但这是一般性的引用，并未具体描述或评价目标论文的能力，属于ordinary_reference。

### 7. 直接亚毫米精度佐证

**引用论文：** A Survey of Wireless Sensing Security From a Role-Based View  
**被引用论文：** Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration  
**建议：** 候选复核  
**置信度：** medium  

#### 原文证据

> passive eavesdropping attacks aim to gain information about the protected area by intercepting the leakage signals that unavoidably emanate from the protected area, e.g., eavesdropping on loudspeakers in the room by capturing **sub-mm level vibration** via RFID **[23]**

#### 对应参考文献（引用论文原文 References 中的条目）

> **[23]** 未解析到引用论文原文 References 条目

#### 原文上下文

> In the following, we provide a classification of attack roles... Fig. 3 depicts different types of attacks... Passive eavesdropping attacks aim to gain information about the protected area by intercepting the leakage signals that unavoidably emanate from the protected area, e.g., eavesdropping on loudspeakers in the room by capturing **sub-mm level vibration** via RFID **[23]**.

#### 亮点评价

该综述在攻击分类中将[23]列为被动窃听攻击实例，明确指出其通过RFID捕获亚毫米级振动实现穿墙窃听扬声器的能力。

#### 评价理由

引文正文明确将[23]作为穿墙窃听示例，且使用了“capturing sub-mm level vibration via RFID”的描述，与目标论文标题和内容一致，无归属风险。 无法从引用论文 References 中解析该编号对应的原始条目，不能推荐纳入。

### 8. 直接亚毫米精度佐证

**引用论文：** A Comprehensive Survey of Side-Channel Sound-Sensing Methods  
**被引用论文：** Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration  
**建议：** 候选复核  
**置信度：** medium  

#### 原文证据

> **Thru-the-wall eavesdropping on loudspeakers via RFID by capturing sub-mm level vibration** **[23]**

#### 对应参考文献（引用论文原文 References 中的条目）

> **[23]** 未解析到引用论文原文 References 条目

#### 原文上下文

> Meanwhile, some studies focus on utilizing RFID for side-channel sound sensing. **Thru-the-wall eavesdropping on loudspeakers via RFID by capturing sub-mm level vibration** **[23]** enables high precision sensing without requiring any dedicated motion sensors.

#### 亮点评价

综述引用[23]时明确指出该工作实现了通过RFID捕捉亚毫米级振动的穿墙窃听。

#### 评价理由

正文直接引用[23]并提及目标论文标题中的'Thru-the-wall eavesdropping'和'sub-mm level vibration'，明确描述了穿墙窃听能力。 无法从引用论文 References 中解析该编号对应的原始条目，不能推荐纳入。

### 9. 直接亚毫米精度佐证

**引用论文：** A Comprehensive Survey of Side-Channel Sound-Sensing Methods  
**被引用论文：** Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration  
**建议：** 候选复核  
**置信度：** medium  

#### 原文证据

> by capturing **sub-mm level vibration** **[23]**

#### 对应参考文献（引用论文原文 References 中的条目）

> **[23]** 未解析到引用论文原文 References 条目

#### 原文上下文

> Meanwhile, some studies focus on utilizing RFID for side-channel sound sensing. **Thru-the-wall eavesdropping on loudspeakers via RFID by capturing sub-mm level vibration** **[23]** enables high precision sensing without requiring any dedicated motion sensors.

#### 亮点评价

综述引用[23]时确认该工作通过捕捉亚毫米级振动实现高精度感知。

#### 评价理由

正文直接引用[23]且明确提到'sub-mm level vibration'，该短语来自目标论文标题，且正文中将其与高精度感知关联，符合亚毫米级精度认定。 无法从引用论文 References 中解析该编号对应的原始条目，不能推荐纳入。

### 10. 直接亚毫米精度佐证

**引用论文：** A Comprehensive Survey of Side-Channel Sound-Sensing Methods  
**被引用论文：** Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration  
**建议：** 候选复核  
**置信度：** medium  

#### 原文证据

> The authors in **[23]** achieve thru-the-wall eavesdropping on loudspeakers by capturing **sub-mm level vibration** of the loudspeaker using RFID.

#### 对应参考文献（引用论文原文 References 中的条目）

> **[23]** 未解析到引用论文原文 References 条目

#### 原文上下文

> From the RFID perspective, some works exploit the phase change of RFID backscattered signals to capture mechanical vibration. ... The authors in **[23]** achieve thru-the-wall eavesdropping on loudspeakers by capturing **sub-mm level vibration** of the loudspeaker using RFID.

#### 亮点评价

该综述指出，文献[23]通过RFID捕获扬声器的亚毫米级振动，实现了隔墙窃听扬声器的能力。

#### 评价理由

正文明确以[23]为锚点，描述了目标论文实现了通过RFID捕捉亚毫米级振动进行隔墙窃听的能力，属于直接的能力认可。 无法从引用论文 References 中解析该编号对应的原始条目，不能推荐纳入。

### 11. 直接亚毫米精度佐证

**引用论文：** A Survey of Wireless Sensing Security From a Role-Based View  
**被引用论文：** Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration  
**建议：** 候选复核  
**置信度：** medium  

#### 原文证据

> **Thru-the-wall eavesdropping on loudspeakers via RFID by capturing sub-mm level vibration** **[23]**

#### 对应参考文献（引用论文原文 References 中的条目）

> **[23]** 未解析到引用论文原文 References 条目

#### 原文上下文

> This paper presents the first comprehensive survey of wireless sensing security from 2004 to early 2025. ... Through a systematic analysis of over 430 publications collected in our open Awesome-WS-Security database, we map the current landscape, ... Project page: https://github.com/Intelligent-Perception-Lab/Awesome-WS-Security.

#### 亮点评价

该综述引用目标论文时明确指出其实现了通过RFID捕获亚毫米级振动以进行穿墙窃听的能力。

#### 评价理由

正文引用[23]明确提及'capturing sub-mm level vibration'并锚定目标论文，符合sub-mm precision claim要求。 无法从引用论文 References 中解析该编号对应的原始条目，不能推荐纳入。

## 四、候选复核附录

### 12. 普通相关工作

**引用论文：** Understanding Privacy Threat for Side-channel Speech Eavesdropping Attack  
**被引用论文：** Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration  
**建议：** 候选复核  
**置信度：** high  

#### 原文证据

> UHF RFID [24, 25, 26]

#### 对应参考文献（引用论文原文 References 中的条目）

> **[26]** C. Wang, L. Xie, Y. Lin, W. Wang, Y. Chen, Y. Bu, K. Zhang, and S. Lu, “Thru-
> the-wall eavesdropping on loudspeakers via rfid by capturing **sub-mm level vibration**,”
> ACM IMWUT (UbiComp) , 2020.
> 50

#### 原文上下文

> RF signals, including WiFi [23], UHF RFID [24, 25, 26], UWB [27], mmWave signals [29, 31, 32, 28, 42, 7], can be considered as a wireless vibrometry to measure the RF signal changes caused by the sound source vibration.

#### 亮点评价

该论文在背景章节将目标文献与其他UHF RFID工作并列，作为无线振动测量的一般性相关工作列举，未作具体评价。

#### 评价理由

该引用是一个包含多个参考文献的组引用，正文未对[26]进行单独描述或评价，仅将其列为UHF RFID侧信道的一般性相关工作。未锚定亚毫米级精度或具体能力，属于普通引用。

### 13. 能力佐证

**引用论文：** Repurposing the Ubiquitous Acoustic Devices for Cross-Modality Sensing  
**被引用论文：** Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration  
**建议：** 候选复核  
**置信度：** high  

#### 原文证据

> Recent research indicates that non-acoustic hardware, such as motion sensors [153, 32, 34, 39, 209, 80], actuators [151, 192, 138], communication devices [255, 240, 271, 133, 254], storage devices [125], radars [52, 75, 268, 238, 288, 279, 54], cameras [63, 141], and instruments [169, 168, 286, 195], can create a side channel to eavesdrop the speech generated by humans or loudspeakers.

#### 对应参考文献（引用论文原文 References 中的条目）

> **[240]** Chuyu Wang, Lei Xie, Yuancan Lin, Wei Wang, Yingying Chen, Yanling Bu, Kai Zhang,
> and Sanglu Lu. Thru-the-wall eavesdropping on loudspeakers via rfid by capturing
> **sub-mm level vibration**. Proceedings of ACM IMWUT (UbiComp), 2020.

#### 原文上下文

> The pervasive use of speech communication devices amplifies the potential threats of speech eavesdropping... Recent research indicates that non-acoustic hardware, such as motion sensors [153, 32, 34, 39, 209, 80], actuators [151, 192, 138], communication devices [255, 240, 271, 133, 254], storage devices [125], radars [52, 75, 268, 238, 288, 279, 54], cameras [63, 141], and instruments [169, 168, 286, 195], can create a side channel to eavesdrop the speech generated by humans or loudspeakers. While these devices are not intended for sound recording, they can capture the unintended acoustic byproducts of speech, potentially enabling the recovery of private conversations.

#### 亮点评价

引用论文将目标论文[240]列为非声学硬件通过侧信道窃听语音的代表性工作之一，但未对其亚毫米级精度或RFID振动感知能力进行具体确认。

#### 评价理由

目标论文[240]被列在通信设备类别中，作为通过侧信道窃听语音的研究示例。引用论文未明确提及亚毫米级感知、RFID振动感知或穿墙窃听的具体能力，属于普通相关工作总结。由于是分组引用且无详细描述，推荐review而非include。

### 14. rfid_loudspeaker_vibration

**引用论文：** RF-Parrot: Wireless Eavesdropping on Wired Audio  
**被引用论文：** Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration  
**建议：** 候选复核  
**置信度：** high  

#### 原文证据

> TagBug places **RFID tags** on the surrounding objects around the loudspeaker and collects the backscattered RFID signal for eavesdropping **[6]**.

#### 对应参考文献（引用论文原文 References 中的条目）

> **[6]** C. Wang, L. Xie, Y . Lin, W. Wang, Y . Chen, Y . Bu, K. Zhang, and S. Lu,
> “Thru-the-wall eavesdropping on loudspeakers via rfid by capturing **sub-
> mm level vibration**,” Proceedings of the ACM on Interactive, Mobile,
> Wearable and Ubiquitous Technologies, vol. 5, no. 4, pp. 1–25, 2021.

#### 原文上下文

> Acoustic signals are mechanical waves that force surrounding elastic objects to vibrate continuously. Researchers harness such phenomenon to investigate various vibration sensors, e.g., accelerometer [34]–[36], laser [7], RFID **[6]**, WiFi [5], mmWave [2]–[4] and videos [8], for audio eavesdropping. ... TagBug places **RFID tags** on the surrounding objects around the loudspeaker and collects the backscattered RFID signal for eavesdropping **[6]**. However, the above vibration-based eavesdropping methods require the audio to be played out by the loudspeaker so that the nearby object’s surface can be driven to vibrate.

#### 亮点评价

本文在相关工作部分将目标论文[6]归类为基于振动的音频窃听方法，指出其利用RFID标签捕获扬声器振动实现窃听，但未对其性能或技术先进性做出明确评价。

#### 评价理由

该证据属于普通相关工作列举，没有明确提及亚毫米精度或特殊能力，且引用标记[6]正确对应目标论文。文中仅将其作为基于RFID的窃听方法之一进行描述，因此归类为ordinary_reference，建议review。

### 15. rfid_loudspeaker_vibration

**引用论文：** FAN-RFID: Exfiltrating Data from Air-Gapped Systems Via Fan-Induced RFID Modulation  
**被引用论文：** Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration  
**建议：** 候选复核  
**置信度：** high  

#### 原文证据

> Recent studies demonstrate that RFID systems can also detect minute environmental vibrations, including acoustic waves[10, 11, 12] and mechanical oscillations[13, 14, 15], by monitoring subtle changes in backscattered signals.

#### 对应参考文献（引用论文原文 References 中的条目）

> **[11]** 未解析到引用论文原文 References 条目

#### 原文上下文

> Recent studies demonstrate that RFID systems can also detect minute environmental vibrations, including acoustic waves[10, 11, 12] and mechanical oscillations[13, 14, 15], by monitoring subtle changes in backscattered signals. This capability suggests that otherwise trusted RFID infrastructure could be repurposed to detect maliciously induced vibrations, such as those generated by a manipulated cooling fan.

#### 亮点评价

引用论文将目标论文作为RFID振动感知领域的代表性工作进行引用，但未展开具体能力，属于一般性相关研究引用。

#### 评价理由

该引用在介绍RFID系统可检测微小环境振动时，将目标论文[11]与其他文献一起作为示例性引用，属于普通相关研究描述，没有明确肯定目标论文的亚毫米级精度或穿墙窃听能力，故判定为ordinary_reference。

### 16. 穿墙窃听能力佐证

**引用论文：** Privacy-preserving human activity sensing: A survey  
**被引用论文：** Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration  
**建议：** 候选复核  
**置信度：** medium  

#### 原文证据

> Eavesdropping on speech via IMU sensors, RF signals, and side-channel signals is widely investigated [50, 51, 52, 53].

#### 对应参考文献（引用论文原文 References 中的条目）

> **[51]** C. Wang, L. Xie, Y. Lin, W. Wang, Y. Chen, Y. Bu, K. Zhang, S. Lu,
> Thru-the-wall eavesdropping on loudspeakers via rfid by capturing **sub-
> mm level vibration**, Proceedings of the ACM on Interactive, Mobile,
> Wearable and Ubiquitous Technologies 5 (4) (2021) 1–25.

#### 原文上下文

> In addition to identity information, the speech content in the audio signal also involves private information. ... Eavesdropping on speech via IMU sensors, RF signals, and side-channel signals is widely investigated [50, 51, 52, 53].

#### 亮点评价

该综述将目标论文列为通过RF信号实现语音窃听的代表性工作之一，确认了其窃听能力。

#### 评价理由

引文将[51]（目标论文）作为RF信号窃听语音的代表性工作之一，虽然为分组引用，但上下文明确提及“Eavesdropping on speech via IMU sensors, RF signals”，且目标论文标题包含“Thru-the-wall eavesdropping on loudspeakers via RFID”，因此可合理判断为through_wall_eavesdropping能力认可。未提及sub-mm，故不归为submm_precision_claim。 成组引用没有单独描述目标论文，需进入候选复核。

### 17. 穿墙窃听能力佐证

**引用论文：** Who Speaks What from Afar: Eavesdropping In-Person Conversations via mmWave Sensing  
**被引用论文：** Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration  
**建议：** 候选复核  
**置信度：** high  

#### 原文证据

> For example, attaching battery-less commercial off-the-shelf **RFID tags** on everyday objects can achieve **through-the-wall sound eavesdropping** **[37]**.

#### 对应参考文献（引用论文原文 References 中的条目）

> **[37]** C. Wang, L. Xie, Y . Lin, W. Wang, Y . Chen, Y . Bu, K. Zhang, and S. Lu,
> “Thru-the-wall eavesdropping on loudspeakers via rfid by capturing **sub-
> mm level vibration**,”Proceedings of the ACM on Interactive, Mobile,
> Wearable and Ubiquitous Technologies, vol. 5, no. 4, pp. 1–25, 2021.

#### 原文上下文

> RF-based sound eavesdropping.Radio frequency signals, such as WiFi [35], [36], RFID **[37]**, [38], and mmWave [2], [8], [15], [39], [40], are popular in sound eavesdropping. Due to the penetrating capabilities of RF signals, they are deployed for undetectable attacks outside the room. For example, attaching battery-less commercial off-the-shelf **RFID tags** on everyday objects can achieve **through-the-wall sound eavesdropping** **[37]**.

#### 亮点评价

引用论文将目标文献归类为RFID穿墙窃听的代表性工作，确认了其通过RFID标签实现穿墙声音窃听的能力。

#### 评价理由

引用论文正文明确指出目标论文实现了through-the-wall sound eavesdropping，但未提及sub-mm精度；属于能力认可但非亚毫米精度佐证。

### 18. 普通相关工作

**引用论文：** Hiding an Ear in Plain Sight: On the Practicality and Implications of Acoustic Eavesdropping with Telecom Fiber Optic Cables  
**被引用论文：** Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration  
**建议：** 候选复核  
**置信度：** high  

#### 原文证据

> RF. ... Radio Frequency Identification (RFID) **[95]**, or by collecting RF emanations from a microphone [96]. Across these studies, the average source-to-attacker distance is about 3.6 m, with some systems reaching up to 8 m [88], [92]. The accuracy of the speech recognition can be as high as 0.94 at 1 m **[95]** or WER = 0.06 at 2 m [96].

#### 对应参考文献（引用论文原文 References 中的条目）

> **[95]** C. Wang, L. Xie, Y . Lin, W. Wang, Y . Chen, Y . Bu, K. Zhang, and S. Lu,
> “Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing
> **Sub-mm Level Vibration**,”Proceedings of the ACM on Interactive,
> Mobile, Wearable and Ubiquitous Technologies, vol. 5, no. 4, pp. 1–25,
> 2021.

#### 原文上下文

> RF. Wi-Fi signals, for example, have been utilized to profile mouth movements [85] and detect loudspeakers' vibrations [86], where the distance between the sound source and the signal transmitter is around 2 m and the accuracy is above 0.8. More recent work has focused on millimeter-wave (mmWave) radar [87], [88], [89], [90], [91], [92], [93], [94], Radio Frequency Identification (RFID) **[95]**, or by collecting RF emanations from a microphone [96]. Across these studies, the average source-to-attacker distance is about 3.6 m, with some systems reaching up to 8 m [88], [92]. The accuracy of the speech recognition can be as high as 0.94 at 1 m **[95]** or WER = 0.06 at 2 m [96].

#### 亮点评价

引用论文在相关工作RF部分提及目标论文[95]，指出其通过RFID实现穿墙窃听，在1米距离语音识别准确率高达0.94。但该引用仅为一般性文献回顾，未对目标论文进行专门评价或方法使用。

#### 评价理由

引用论文在相关工作段落的RF小节中，将目标论文与其他基于RF的窃听方法（如Wi-Fi、雷达）并列列举，并引用了其高精度语音识别性能。但该引用属于普通文献综述中的概括性介绍，未对目标论文进行深入分析或直接比较，因此归类为ordinary_reference，建议review。

### 19. rfid_loudspeaker_vibration

**引用论文：** CSI2Dig: Recovering Digit Content from Smartphone Loudspeakers Using Channel State Information  
**被引用论文：** Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration  
**建议：** 候选复核  
**置信度：** high  

#### 原文证据

> RF-based schemes focus on using high-frequency signals to characterize vibrations induced by the loudspeaker. These schemes mainly utilize millimeter waves [8], [9], [10], [45], [46], [47], [48], [49], RFID signals [11], [12], **[13]**, electromagnetic signals [15], [16], [17], [18], and WiFi signals [14], among other RF signals [50].

#### 对应参考文献（引用论文原文 References 中的条目）

> **[13]** C. Wang, L. Xie, Y . Lin, W. Wang, Y . Chen, Y . Bu, K. Zhang, and S. Lu,
> “Thru-the-wall eavesdropping on loudspeakers via rfid by capturing **sub-
> mm level vibration**,” Proceedings of the ACM on Interactive, Mobile,
> Wearable and Ubiquitous Technologies, vol. 5, no. 4, pp. 1–25, 2022.

#### 原文上下文

> RF-based schemes focus on using high-frequency signals to characterize vibrations induced by the loudspeaker. These schemes mainly utilize millimeter waves [8], [9], [10], [45], [46], [47], [48], [49], RFID signals [11], [12], **[13]**, electromagnetic signals [15], [16], [17], [18], and WiFi signals [14], among other RF signals [50]. These schemes typically require specialized equipment or complex hardware configurations.

#### 亮点评价

该文将目标论文列为基于RFID信号的窃听方案之一，作为相关技术背景提及，未展开具体描述。

#### 评价理由

目标论文被归入RFID组群引用，作为RFID相关工作的一个实例，没有单独描述其方法或贡献，属于普通列举。

### 20. 普通相关工作

**引用论文：** Repurposing optical mice for acoustic eavesdropping  
**被引用论文：** Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration  
**建议：** 候选复核  
**置信度：** high  

#### 原文证据

> RFID-based methods have also been explored, with Wang et al. **[13]** showing how audio can be intercepted via RFID.

#### 对应参考文献（引用论文原文 References 中的条目）

> **[13]** C. Wang, L. Xie, Y . Lin, W. Wang, Y . Chen, Y . Bu, K. Zhang, and S. Lu,
> “Thru-the-wall eavesdropping on loudspeakers via rfid by capturing **sub-
> mm level vibration**,” Proceedings of the ACM on Interactive, Mobile,
> Wearable and Ubiquitous Technologies, vol. 5, no. 4, pp. 1–25, 2021.

#### 原文上下文

> Wireless signals have also been exploited by researchers for sound recovery [8]–**[13]**. ... RFID-based methods have also been explored, with Wang et al. **[13]** showing how audio can be intercepted via RFID. However, these systems are often affected by environmental factors and require expensive equipment to send and receive signals like mmWave, limiting their practicality.

#### 亮点评价

该文在相关工作部分提及目标论文展示了通过RFID拦截音频的能力。

#### 评价理由

引文仅在相关工作列表中简要提及RFID方法，属于普通引用，未对目标论文的具体能力（如亚毫米级精度、穿墙等）进行确认或评价。

### 21. 穿墙窃听能力佐证

**引用论文：** SPACE: Speaker Adaptation for Acoustic Eavesdropping Using mmWave Radio Signals  
**被引用论文：** Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration  
**建议：** 候选复核  
**置信度：** high  

#### 原文证据

> As for RFID-based methods, researchers have explored the possibility of using COTS **RFID tags** to perform the thru-the-wall eavesdropping on the loudspeaker **[50]**.

#### 对应参考文献（引用论文原文 References 中的条目）

> **[50]** C. Wang, L. Xie, Y . Lin, W. Wang, Y . Chen, Y . Bu, K. Zhang, and S. Lu,
> “Thru-the-wall eavesdropping on loudspeakers via rfid by capturing **sub-
> mm level vibration**,” Proceedings of the ACM on Interactive, Mobile,
> Wearable and Ubiquitous Technologies, vol. 5, no. 4, pp. 1–25, 2021.

#### 原文上下文

> RF-based audio sensing. Compared with vision and motion sensor related solutions, RF is immune to lighting conditions and occlusions and is more sensitive to vibrations. The RF-based methods can be classified according to the RF technologies used, including WiFi, RFID, and mmWave. Wei et al. [2] implemented an audio sensing system with a WiFi antenna array for RF-based speech recovery. Wang et al. [49] implemented WiHear to detect and analyze radio reflections from mouth movements based on WiFi signals. As for RFID-based methods, researchers have explored the possibility of using COTS **RFID tags** to perform the thru-the-wall eavesdropping on the loudspeaker **[50]**. Chen et al. [51] attached a low-cost **RFID tag** on the glass bridge to sense subtle facial speech dynamics and thereby achieve live voice eavesdropping.

#### 亮点评价

引用论文在相关工作部分将目标论文列为RFID音频传感的代表性工作，提及了其通过RFID标签进行穿墙扬声器窃听的技术方向，属于普通引用，未对目标论文的亚毫米级振动感知能力进行明确确认或评价。

#### 评价理由

该引用位于相关工作的RF-based audio sensing段落中，仅仅提及RFID方法进行了through-the-wall扬声器窃听的研究，没有具体描述或确认目标论文的sub-mm振动感知能力，也未提及RFID、sub-mm等关键词与目标论文的关联，因此属于普通引用。

### 22. rfid_loudspeaker_vibration

**引用论文：** Sensing Metal Coil Vibration of Headsets for Eavesdropping on Online Conversations With Out-of-Vocabulary Words Using RFID  
**被引用论文：** Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration  
**建议：** 候选复核  
**置信度：** high  

#### 原文证据

> some works use RF signals, such as Wi-Fi[29], mmWave[2], and RFID**[3]**, [4], [30], to capture object vibration for sensing speaker-produced sound[1], [2], **[3]**, [29], [30] or capture body motions for sensing human-speaking sound[4].

#### 对应参考文献（引用论文原文 References 中的条目）

> **[3]** C. Wang et al., “Thru-the-wall eavesdropping on loudspeakers via RFID by
> capturing **sub-mm level vibration**,”Proc. ACM Interact. Mobile Wearable
> Ubiquitous Technol., vol. 5, no. 4, pp. 1–25, 2021.

#### 原文上下文

> Sensing sound through non-acoustic sensors: With the development of IoT technology, studies about sound sensing through non-acoustic sensors receive lots of attention. ... On the other hand, some works use RF signals, such as Wi-Fi[29], mmWave[2], and RFID**[3]**, [4], [30], to capture object vibration for sensing speaker-produced sound[1], [2], **[3]**, [29], [30] or capture body motions for sensing human-speaking sound[4]. However, due to sensor limitations, these methods can sense either speaker-produced or human-speaking sound, but not both simultaneously.

#### 亮点评价

目标论文在相关工作中被列入RF信号感知声音的文献群，但未获得单独阐述或特别评价。

#### 评价理由

该引用是典型的相关工作分类列举，目标论文与其他RFID工作一同被提及，作为RF信号用于振动感知的例子，没有单独描述其方法或突出贡献，属于普通引用。

### 23. 能力佐证

**引用论文：** Sensing Metal Coil Vibration of Headsets for Eavesdropping on Online Conversations With Out-of-Vocabulary Words Using RFID  
**被引用论文：** Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration  
**建议：** 候选复核  
**置信度：** medium  

#### 原文证据

> **Thru-the-wall eavesdropping on loudspeakers via RFID by capturing sub-mm level vibration**

#### 对应参考文献（引用论文原文 References 中的条目）

> **[3]** C. Wang et al., “Thru-the-wall eavesdropping on loudspeakers via RFID by
> capturing **sub-mm level vibration**,”Proc. ACM Interact. Mobile Wearable
> Ubiquitous Technol., vol. 5, no. 4, pp. 1–25, 2021.

#### 原文上下文

> Related work: ... some works use RF signals, such as Wi-Fi[29], mmWave[2], and RFID**[3]**, [4], [30], to capture object vibration for sensing speaker-produced sound[1], [2], **[3]**, [29], [30] or capture body motions for sensing human-speaking sound[4]. However, due to sensor limitations, these methods can sense either speaker-produced or human-speaking sound, but not both simultaneously.

#### 亮点评价

目标论文《Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration》被作为RFID振动感知窃听的代表性工作引用，表明其在亚毫米级振动感知和穿墙窃听方面的能力得到认可。

#### 评价理由

引用论文在相关工作部分直接提到目标论文的标题，该标题明确包含“Thru-the-wall”、“sub-mm level vibration”和“eavesdropping”等关键能力描述，且引用标记[3]正确对应目标论文。虽然没有给出详细评价，但认可了其通过墙和亚毫米级振动窃听的能力。 推荐纳入要求正文证据句直接包含目标引用编号。

### 24. 能力佐证

**引用论文：** Multi-User Behavioral Privacy Filtering for mmWave Radar Sensing  
**被引用论文：** Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration  
**建议：** 候选复核  
**置信度：** high  

#### 原文证据

> By measuring the subtle vibrations of objects, mmWave [22], [23], [24] and RFID **[25]** technologies can eavesdrop on human speech.

#### 对应参考文献（引用论文原文 References 中的条目）

> **[25]** C. Wang et al., “Thru-the-wall eavesdropping on loudspeakers via RFID
> by capturing **sub-mm level vibration**,” in Proc. ACM Interactive, Mobile,
> Wearable Ubiquitous Technol., vol. 5, no. 4, pp. 1–25, 2021.

#### 原文上下文

> The application of radio frequency (RF) technology is becoming increasingly widespread, bringing along with it concerns regarding security and privacy. By measuring the subtle vibrations of objects, mmWave [22], [23], [24] and RFID **[25]** technologies can eavesdrop on human speech.

#### 亮点评价

目标论文被引用为RFID领域能够通过测量物体微小振动实现语音窃听的代表工作之一。

#### 评价理由

正文引用[25]（目标论文）作为RFID技术的例子，说明RFID可通过测量物体的微小振动来窃听人类语音。但该描述是概括性表述，未明确提及目标论文的具体贡献如亚毫米级精度或隔墙能力，属于普通相关工作总结。attribution_risk：引文为分组引用，且未将sub-mm直接锚定到目标论文。

### 25. 普通相关工作

**引用论文：** A Comprehensive Survey of Side-Channel Sound-Sensing Methods  
**被引用论文：** Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration  
**建议：** 候选复核  
**置信度：** high  

#### 原文证据

> Some representative works include vibration-based approaches using RFID **[23]**[24][25], mmWave [26]–[28], laser [29], etc.

#### 对应参考文献（引用论文原文 References 中的条目）

> **[23]** 未解析到引用论文原文 References 条目

#### 原文上下文

> Based on the classification of sensing platforms, side-channel sound-sensing methods can be divided into different categories. Some representative works include vibration-based approaches using RFID **[23]**[24][25], mmWave [26]–[28], laser [29], etc.

#### 亮点评价

该综述将目标论文作为基于RFID的振动感知代表性工作之一进行引用。

#### 评价理由

该引文出现在分组列举中，且描述为'vibration-based approaches using RFID'，未单独描述目标论文的贡献或能力，属于普通相关工作列举。

### 26. rfid_loudspeaker_vibration

**引用论文：** Vib2audio: Robust Sound Recovery With Micro Vibration Sensing Via mmWave Radar  
**被引用论文：** Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration  
**建议：** 候选复核  
**置信度：** high  

#### 原文证据

> For instance, Wang et al. **[12]** utilized radio-frequency identification (RFID) to receive the speaker's vibration signal in the environment.

#### 对应参考文献（引用论文原文 References 中的条目）

> **[12]** C. Wang et al., “Thru-the-wall eavesdropping on loudspeakers via
> RFID by capturing **sub-mm level vibration**,” Proc. ACM Interact.,
> Mobile, Wearable Ubiquitous Technol., vol. 5, no. 4, pp. 1–25,
> Dec. 2021.

#### 原文上下文

> The vibration of a sound source travels through the air as sound waves, causing vibrations in the surrounding objects. The method of indirect voice recovery by sensing the vibrations of surrounding objects can be seen as passive sensing. For instance, Wang et al. **[12]** utilized radio-frequency identification (RFID) to receive the speaker's vibration signal in the environment. This approach requires a preinstalled tag in the victim's room.

#### 亮点评价

引用论文在相关工作部分将目标论文列为利用RFID进行扬声器振动感知的被动感知方法实例。

#### 评价理由

引用出现在被动感知部分的一般性列举中，仅描述其利用RFID接收振动信号，未提及亚毫米精度、穿墙或具体能力，属于普通相关工作引用。

### 27. rfid_loudspeaker_vibration

**引用论文：** OISMic: Acoustic Eavesdropping Exploiting Sound-induced OIS Vibrations in Smartphones  
**被引用论文：** Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration  
**建议：** 候选复核  
**置信度：** high  

#### 原文证据

> Moreover, researchers also use **RFID tags** **[15]** and mmWave radar [16] to detect reflected vibration signals for eavesdropping.

#### 对应参考文献（引用论文原文 References 中的条目）

> **[15]** 未解析到引用论文原文 References 条目

#### 原文上下文

> Wireless-based approaches spy on voice information by analyzing wireless signals reflected from vibrating objects. For instance, Wei et al. [14] inspects subtle disturbances on a target loudspeaker and recovers the audio signal by analyzing the received signal strength (RSS) readings of WiFi packets. Moreover, researchers also use **RFID tags** **[15]** and mmWave radar [16] to detect reflected vibration signals for eavesdropping.

#### 亮点评价

目标论文在相关工作列表中被提及作为RFID窃听的一个示例，但未展开讨论其具体贡献。

#### 评价理由

该引用仅为相关工作中的普通列举，未提供任何关于目标论文的具体能力描述（如sub-mm精度、通过墙窃听等），属于ordinary_reference，不应评为include。

### 28. 普通相关工作

**引用论文：** A Vibration Signal Enhancement Scheme for mmWave-Based Sound Eavesdropping  
**被引用论文：** Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration  
**建议：** 候选复核  
**置信度：** high  

#### 原文证据

> Recently, wireless-based methods have gained significant attention owing to their ability to penetrate barriers and operate independently of light conditions. These techniques leverage changes in reflected wireless signals, such as WiFi [8], RFID **[9]**, and mmWave [10], to infer sound-induced vibrations, enabling the recreation of sound information.

#### 对应参考文献（引用论文原文 References 中的条目）

> **[9]** C. Wang, L. Xie, Y . Lin, W. Wang, Y . Chen, Y . Bu, K. Zhang, and S. Lu,
> “Thru-the-wall eavesdropping on loudspeakers via rﬁd by capturing **sub-
> mm level vibration**,” Proceedings of the ACM on Interactive, Mobile,
> Wearable and Ubiquitous Technologies, vol. 5, no. 4, pp. 1–25, 2021.

#### 原文上下文

> Recently, wireless-based methods have gained significant attention owing to their ability to penetrate barriers and operate independently of light conditions. These techniques leverage changes in reflected wireless signals, such as WiFi [8], RFID **[9]**, and mmWave [10], to infer sound-induced vibrations, enabling the recreation of sound information.

#### 亮点评价

引用论文将目标论文列为无线声音窃听技术的一种，但未做具体展开。

#### 评价理由

该引文仅在列举无线方法时提到 RFID [9]，属于普通的相关工作列举，未对目标论文的亚毫米级精度或具体能力进行描述。因此判定为普通引用，推荐 review。

### 29. 普通相关工作

**引用论文：** RadEye: Tracking Eye Motion Using FMCW Radar  
**被引用论文：** Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration  
**建议：** 候选复核  
**置信度：** high  

#### 原文证据

> Low-frequency radio signals have been widely leveraged for fine-grained human activity recognition (HAR), such as Wi-Fi sensing [9, 15, 19, 20, 36, 37], RFID sensing [35, 43], and 4G/5G sensing [7, 40].

#### 对应参考文献（引用论文原文 References 中的条目）

> **[35]** Chuyu Wang, Lei Xie, Yuancan Lin, Wei Wang, Yingying Chen, Yanling Bu, Kai 
> Zhang, and Sanglu Lu. 2021. Thru-the-wall eavesdropping on loudspeakers via 
> RFID by capturing **sub-mm level vibration**. Proceedings of the ACM on Interactive, 
> Mobile, Wearable and Ubiquitous Technologies 5, 4 (2021), 1–25. doi:10.1145/ 
> 3494975

#### 原文上下文

> Low-frequency radio signals have been widely leveraged for fine-grained human activity recognition (HAR), such as Wi-Fi sensing [9, 15, 19, 20, 36, 37], RFID sensing [35, 43], and 4G/5G sensing [7, 40].

#### 亮点评价

该文在介绍低频射频信号用于人体活动识别时，将目标论文列为RFID感知的代表工作之一。

#### 评价理由

引文仅在列举低频射频感知工作时，作为RFID感知的示例之一被提及，属于普通相关工作列举，未体现目标论文的具体能力或方法。

### 30. 穿墙窃听能力佐证

**引用论文：** Who Speaks What from Afar: Eavesdropping In-Person Conversations via mmWave Sensing  
**被引用论文：** Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration  
**建议：** 候选复核  
**置信度：** high  

#### 原文证据

> RF-based sound eavesdropping. Radio frequency signals, such as WiFi [35], [36], RFID **[37]**, [38], and mmWave [2], [8], [15], [39], [40], are popular in sound eavesdropping. Due to the penetrating capabilities of RF signals, they are deployed for undetectable attacks outside the room. For example, attaching battery-less commercial off-the-shelf **RFID tags** on everyday objects can achieve **through-the-wall sound eavesdropping** **[37]**.

#### 对应参考文献（引用论文原文 References 中的条目）

> **[37]** C. Wang, L. Xie, Y . Lin, W. Wang, Y . Chen, Y . Bu, K. Zhang, and S. Lu,
> “Thru-the-wall eavesdropping on loudspeakers via rfid by capturing **sub-
> mm level vibration**,”Proceedings of the ACM on Interactive, Mobile,
> Wearable and Ubiquitous Technologies, vol. 5, no. 4, pp. 1–25, 2021.

#### 原文上下文

> RF-based sound eavesdropping. Radio frequency signals, such as WiFi [35], [36], RFID **[37]**, [38], and mmWave [2], [8], [15], [39], [40], are popular in sound eavesdropping. Due to the penetrating capabilities of RF signals, they are deployed for undetectable attacks outside the room. For example, attaching battery-less commercial off-the-shelf **RFID tags** on everyday objects can achieve **through-the-wall sound eavesdropping** **[37]**.

#### 亮点评价

该论文在相关工作部分引用目标论文作为RFID穿墙声学窃听的代表性工作，确认了其通过RFID标签实现穿墙窃听的能力。

#### 评价理由

引文[37]在Related Work段落中作为RFID窃听的一个示例被提及，描述了穿墙能力，但没有明确提及亚毫米精度或用于方法/基线对比。属于常规相关工作综述，不满足具体使用或突出能力认定的条件。

### 31. 穿墙窃听能力佐证

**引用论文：** RFNOID: Protecting RFID Motion Privacy via Metasurface  
**被引用论文：** Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration  
**建议：** 候选复核  
**置信度：** high  

#### 原文证据

> researchers have demonstrated the feasibility of using commodity RFID devices for **through-wall eavesdropping** [15, 17].

#### 对应参考文献（引用论文原文 References 中的条目）

> **[15]** C. Wang, L. Xie, Y . Lin, W. Wang, Y . Chen, Y . Bu, K. Zhang, and S. Lu,
> “Thru-the-wall eavesdropping on loudspeakers via rfid by capturing **sub-
> mm level vibration**,” Proc. of ACM IMWUT , 2021.

#### 原文上下文

> Many physiological features, e.g., respiration [9] and facial dynamics [35], and behavioral features, e.g., gait [36] and handshake [37], can be captured by RFID signals for human authentication and identification. In addition, researchers have demonstrated the feasibility of using commodity RFID devices for **through-wall eavesdropping** [15, 17]. Thus, it is crucial to implement privacy measures to secure RFID sensing systems.

#### 亮点评价

目标论文[15]被引文作为通过RFID实现穿墙窃听的可行性示例在相关工作部分提及。

#### 评价理由

引用[15]仅作为通过RFID实现穿墙窃听的可行性示例，属于普通的related work列举，未对目标论文的specific capability做详细描述或评分。

### 32. rfid_loudspeaker_vibration

**引用论文：** Sensing Metal Coil Vibration of Headsets for Eavesdropping on Online Conversations With Out-of-Vocabulary Words Using RFID  
**被引用论文：** Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration  
**建议：** 候选复核  
**置信度：** low  

#### 原文证据

> On the other hand, some works use RF signals, such as Wi-Fi[29], mmWave[2], and RFID**[3]**, [4], [30], to capture object vibration for sensing speaker-produced sound[1], [2], **[3]**, [29], [30] or capture body motions for sensing human-speaking sound[4].

#### 对应参考文献（引用论文原文 References 中的条目）

> **[3]** C. Wang et al., “Thru-the-wall eavesdropping on loudspeakers via RFID by
> capturing **sub-mm level vibration**,”Proc. ACM Interact. Mobile Wearable
> Ubiquitous Technol., vol. 5, no. 4, pp. 1–25, 2021.

#### 原文上下文

> On the other hand, some works use RF signals, such as Wi-Fi[29], mmWave[2], and RFID**[3]**, [4], [30], to capture object vibration for sensing speaker-produced sound[1], [2], **[3]**, [29], [30] or capture body motions for sensing human-speaking sound[4]. However, due to sensor limitations, these methods can sense either speaker-produced or human-speaking sound, but not both simultaneously.

#### 亮点评价

该论文将目标论文列为RFID振动感测的代表性工作之一，但未对其能力进行单独强调。

#### 评价理由

引用论文在与许多其他文献的并列引用中提及目标论文，属于分组引用。没有单独描述目标论文的贡献或能力，存在归因风险。因此设为review，claim_type为capability_recognition。

### 33. 普通相关工作

**引用论文：** Understanding Privacy Threat for Side-channel Speech Eavesdropping Attack  
**被引用论文：** Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration  
**建议：** 候选复核  
**置信度：** high  

#### 原文证据

> RF signals, including WiFi [23], UHF RFID [24, 41, 25, 26], UWB [27], mmWave signals [29, 31, 32, 28, 42, 7], can be considered as a wireless vibrometry to measure the RF signal changes caused by the sound source vibration.

#### 对应参考文献（引用论文原文 References 中的条目）

> **[26]** C. Wang, L. Xie, Y. Lin, W. Wang, Y. Chen, Y. Bu, K. Zhang, and S. Lu, “Thru-
> the-wall eavesdropping on loudspeakers via rfid by capturing **sub-mm level vibration**,”
> ACM IMWUT (UbiComp) , 2020.
> 50

#### 原文上下文

> RF-based SSEA. RF signals, including WiFi [23], UHF RFID [24, 41, 25, 26], UWB [27], mmWave signals [29, 31, 32, 28, 42, 7], can be considered as a wireless vibrometry to measure the RF signal changes caused by the sound source vibration.

#### 亮点评价

引用论文将[23]列为RF-based侧信道窃听的代表性工作之一，未对其性能或能力进行具体肯定。

#### 评价理由

该句将[23]作为WiFi为代表的外部窃听技术之一，在概述RF-based SSEA时以列表形式引用，未对[23]进行具体描述或评价，属于普通相关引用。

### 34. 普通相关工作

**引用论文：** A Vibration Signal Enhancement Scheme for mmWave-Based Sound Eavesdropping  
**被引用论文：** Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration  
**建议：** 候选复核  
**置信度：** high  

#### 原文证据

> These techniques leverage changes in reflected wireless signals, such as WiFi [8], RFID **[9]**, and mmWave [10], to infer sound-induced vibrations, enabling the recreation of sound information.

#### 对应参考文献（引用论文原文 References 中的条目）

> **[9]** C. Wang, L. Xie, Y . Lin, W. Wang, Y . Chen, Y . Bu, K. Zhang, and S. Lu,
> “Thru-the-wall eavesdropping on loudspeakers via rﬁd by capturing **sub-
> mm level vibration**,” Proceedings of the ACM on Interactive, Mobile,
> Wearable and Ubiquitous Technologies, vol. 5, no. 4, pp. 1–25, 2021.

#### 原文上下文

> Recently, wireless-based methods have gained significant attention owing to their ability to penetrate barriers and operate independently of light conditions. These techniques leverage changes in reflected wireless signals, such as WiFi [8], RFID **[9]**, and mmWave [10], to infer sound-induced vibrations, enabling the recreation of sound information.

#### 亮点评价

该文在列举无线窃听技术时，将目标论文作为RFID方法的代表提及。

#### 评价理由

证据为分组引用中的普通列举，无具体描述，未锚定sub-mm或through-wall等关键词，属于普通的related work引用。

### 35. rfid_loudspeaker_vibration

**引用论文：** RF-Parrot: Wireless Eavesdropping on Wired Audio  
**被引用论文：** Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration  
**建议：** 候选复核  
**置信度：** high  

#### 原文证据

> Tag-Bug places **RFID tags** on the surrounding objects around the loudspeaker and collects the backscattered RFID signal for eavesdropping **[6]**.

#### 对应参考文献（引用论文原文 References 中的条目）

> **[6]** C. Wang, L. Xie, Y . Lin, W. Wang, Y . Chen, Y . Bu, K. Zhang, and S. Lu,
> “Thru-the-wall eavesdropping on loudspeakers via rfid by capturing **sub-
> mm level vibration**,” Proceedings of the ACM on Interactive, Mobile,
> Wearable and Ubiquitous Technologies, vol. 5, no. 4, pp. 1–25, 2021.

#### 原文上下文

> AccEar employs the built-in accelerometer in the smartphone, which is sensitive to the mechanical wave caused by the phone’s loudspeaker, to reconstruct the played audio [35]. Tag-Bug places **RFID tags** on the surrounding objects around the loudspeaker and collects the backscattered RFID signal for eavesdropping **[6]**. mmMIC realizes speech recognition directly from the mouse and throat reflected mmWave signal [37]. However, the above vibration-based eavesdropping methods require the audio to be played out by the loudspeaker so that the nearby object’s surface can be driven to vibrate.

#### 亮点评价

引文在相关工作中提到目标论文（Tag-Bug），指出其通过RFID标签实现振动窃听，但未展开评价其亚毫米精度。

#### 评价理由

引用句中[6]用于支撑Tag-Bug的RFID窃听方法，但该句仅作为相关工作列举，未具体肯定目标论文的sub-mm精度或能力，且引用标记为[6]而非[23]。根据规则，普通相关工作应归类为ordinary_reference，且标记不一致应设置为exclude或review。此处标记误认为[6]但原任务要求TARGET_REFERENCE_MARKER为[23]，实际全文引用为[6]，故判断为false_positive风险，但考虑到原文确为相关工作提及，推荐review。

### 36. 普通相关工作

**引用论文：** Hiding an Ear in Plain Sight: On the Practicality and Implications of Acoustic Eavesdropping with Telecom Fiber Optic Cables  
**被引用论文：** Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration  
**建议：** 候选复核  
**置信度：** high  

#### 原文证据

> RF. ... Radio Frequency Identification (RFID) **[95]** ...

#### 对应参考文献（引用论文原文 References 中的条目）

> **[95]** C. Wang, L. Xie, Y . Lin, W. Wang, Y . Chen, Y . Bu, K. Zhang, and S. Lu,
> “Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing
> **Sub-mm Level Vibration**,”Proceedings of the ACM on Interactive,
> Mobile, Wearable and Ubiquitous Technologies, vol. 5, no. 4, pp. 1–25,
> 2021.

#### 原文上下文

> RF. Wi-Fi signals, for example, have been utilized to profile mouth movements [85] and detect loudspeakers’ vibrations [86]... More recent work has focused on millimeter-wave (mmWave) radar [87]–[94], Radio Frequency Identification (RFID) **[95]**, or by collecting RF emanations from a microphone [96]. Across these studies, the average source-to-attacker distance is about 3.6 m, with some systems reaching up to 8 m [88], [92]. The accuracy of the speech recognition can be as high as 0.94 at 1 m **[95]** or WER = 0.06 at 2 m [96].

#### 亮点评价

目标论文被列为RF侧信道声学窃听的代表性工作之一，但未对其方法或性能进行单独评价。

#### 评价理由

该引用出现在相关工作部分，将[95]与其他RF方法（Wi-Fi、mmWave、RFID）一并列举，仅提及RFID方法和最高准确率0.94，但未具体说明[95]的贡献或将其与其他方法区分，属于普通相关工作的综述性引用。

### 37. performance_comparison

**引用论文：** Rf sensing security and malicious exploitation: A comprehensive survey  
**被引用论文：** Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration  
**建议：** 候选复核  
**置信度：** medium  

#### 原文证据

> Tag-Bug **[102]** ... 4m ✓ H # CA 2kHz Word Recognition

#### 对应参考文献（引用论文原文 References 中的条目）

> **[102]** C. Wang, L. Xie, Y . Lin, W. Wang, Y . Chen, Y . Bu, K. Zhang,
> and S. Lu, “Thru-the-wall eavesdropping on loudspeakers via RFID
> by capturing **sub-mm level vibration**,” Proceedings of the ACM on
> Interactive, Mobile, Wearable and Ubiquitous Technologies , vol. 5,
> no. 4, pp. 1–25, 2021.

#### 原文上下文

> Tag-Bug **[102]** 2021 Loudspeaker 920MHz & 2.4GHz (RFID&USRP N210) 4m ✓ H # CA 2kHz Word Recognition

#### 亮点评价

引用论文在对比表中列出目标论文Tag-Bug的性能指标：4米距离、支持穿墙、无需训练、CA指标、2kHz采样率、单词识别。

#### 评价理由

在对比表格中，Tag-Bug被列出并给出性能参数（距离4米，穿墙，无训练，CA指标，2kHz采样率，单词识别），构成性能比较。 正文证据缺少具体比较或性能指标表述。

### 38. 普通相关工作

**引用论文：** A Survey of Wireless Sensing Security From a Role-Based View  
**被引用论文：** Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration  
**建议：** 候选复核  
**置信度：** low  

#### 原文证据

> crucial for healthcare **[23]**

#### 对应参考文献（引用论文原文 References 中的条目）

> **[23]** 未解析到引用论文原文 References 条目

#### 原文上下文

> Compared to traditional sensors, it offers advantages: (1) Non-contact and non-invasive: It enables sensing with fewer privacy concerns than CMOS sensors, crucial for healthcare **[23]** ...

#### 亮点评价

该综述在介绍无线感知优势时，引用[23]作为非接触感知在医疗保健中应用的示例，但未展开具体技术细节。

#### 评价理由

这里[23]被用作非接触感知在医疗保健中重要性的一个例子，但没有具体描述目标论文的方法或能力，属于普通引用，不应作为亚毫米能力佐证。

### 39. rfid_loudspeaker_vibration

**引用论文：** Vib2audio: Robust Sound Recovery With Micro Vibration Sensing Via mmWave Radar  
**被引用论文：** Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration  
**建议：** 候选复核  
**置信度：** high  

#### 原文证据

> For instance, Wang et al. **[12]** utilized radio-frequency identification (RFID) to receive the speaker’s vibration signal in the environment.

#### 对应参考文献（引用论文原文 References 中的条目）

> **[12]** C. Wang et al., “Thru-the-wall eavesdropping on loudspeakers via
> RFID by capturing **sub-mm level vibration**,” Proc. ACM Interact.,
> Mobile, Wearable Ubiquitous Technol., vol. 5, no. 4, pp. 1–25,
> Dec. 2021.

#### 原文上下文

> The method of indirect voice recovery by sensing the vibrations of surrounding objects can be seen as passive sensing. For instance, Wang et al. **[12]** utilized radio-frequency identification (RFID) to receive the speaker’s vibration signal in the environment. This approach requires a preinstalled tag in the victim’s room.

#### 亮点评价

引用论文在相关工作中将目标论文列为被动声音恢复的代表方法，未提供具体评价或佐证。

#### 评价理由

引用论文在被动感知的上下文中将目标论文作为示例提及，描述了其通过RFID感知扬声器振动的方法，但未明确评价其亚毫米精度或通过墙窃听能力，属于普通的相关工作列举。

### 40. 穿墙窃听能力佐证

**引用论文：** A Batteryless Wireless Microphone Using RF Backscatter  
**被引用论文：** Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration  
**建议：** 候选复核  
**置信度：** medium  

#### 原文证据

> They can offer capabilities like through-wall sensing **[41]**

#### 对应参考文献（引用论文原文 References 中的条目）

> **[41]** Chuyu Wang, Lei Xie, Yuancan Lin, Wei Wang, Yingying Chen, Yanling Bu, Kai Zhang, and Sanglu Lu. 2021. Thru-the-wall eavesdropping
> on loudspeakers via RFID by capturing **sub-mm level vibration**.Proceedings of the ACM on Interactive, Mobile, Wearable and Ubiquitous
> Technologies5, 4 (2021), 1–25.

#### 原文上下文

> One popular approach is radar-based sound Sensing. Systems like RadioMic [20, 21], Radio2Speech [54], mmspy [3], mmecho [11], RFMic-Phone [32], and others [7–9, 38–40, 43–45, 49] use mmWave radar to detect minute vibrations caused by sound waves. They can offer capabilities like through-wall sensing **[41]** and noise resilience [23, 25], sometimes combining radar with traditional microphones [32].

#### 亮点评价

该引用论文在雷达声学感知的相关工作段落中引用了目标论文（[41]），表明其在通过墙壁感应方面的工作。

#### 评价理由

正文中只出现[41]作为 through-wall sensing 能力的示例之一，属于普通相关工作中列表式引用。未单独描述目标论文的具体方法或能力，attribution 风险高。

### 41. rfid_loudspeaker_vibration

**引用论文：** OISMic: Acoustic Eavesdropping Exploiting Sound-induced OIS Vibrations in Smartphones  
**被引用论文：** Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration  
**建议：** 候选复核  
**置信度：** high  

#### 原文证据

> researchers also use **RFID tags** **[15]** and mmWave radar [16] to detect reflected vibration signals for eavesdropping.

#### 对应参考文献（引用论文原文 References 中的条目）

> **[15]** 未解析到引用论文原文 References 条目

#### 原文上下文

> Wireless-based. Wireless-based approaches spy on voice information by analyzing wireless signals reflected from vibrating objects. For instance, Wei et al. [14] inspects subtle disturbances on a target loudspeaker and recovers the audio signal by analyzing the received signal strength (RSS) readings of WiFi packets. Moreover, researchers also use **RFID tags** **[15]** and mmWave radar [16] to detect reflected vibration signals for eavesdropping. These methods enable acoustic eavesdropping through physical barriers on various wireless devices, but require stable wireless conditions and advanced signal processing, potentially lacking robustness in complex environments.

#### 亮点评价

该论文在无线窃听相关工作部分提及目标论文，将其作为使用RFID标签检测反射振动信号进行窃听的一种方法，但未展开讨论。

#### 评价理由

该引用是普通的相关工作列举，仅说明RFID标签可用于窃听，没有明确提及亚毫米级精度或具体能力，且与mmWave雷达并列在分组引用中，存在归属风险。

### 42. 穿墙窃听能力佐证

**引用论文：** Who Speaks What from Afar: Eavesdropping In-Person Conversations via mmWave Sensing  
**被引用论文：** Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration  
**建议：** 候选复核  
**置信度：** medium  

#### 原文证据

> attaching battery-less commercial off-the-shelf **RFID tags** on everyday objects can achieve **through-the-wall sound eavesdropping** **[37]**

#### 对应参考文献（引用论文原文 References 中的条目）

> **[37]** C. Wang, L. Xie, Y . Lin, W. Wang, Y . Chen, Y . Bu, K. Zhang, and S. Lu,
> “Thru-the-wall eavesdropping on loudspeakers via rfid by capturing **sub-
> mm level vibration**,”Proceedings of the ACM on Interactive, Mobile,
> Wearable and Ubiquitous Technologies, vol. 5, no. 4, pp. 1–25, 2021.

#### 原文上下文

> RF-based sound eavesdropping. Radio frequency signals, such as WiFi [35], [36], RFID **[37]**, [38], and mmWave [2], [8], [15], [39], [40], are popular in sound eavesdropping. ... For example, attaching battery-less commercial off-the-shelf **RFID tags** on everyday objects can achieve **through-the-wall sound eavesdropping** **[37]**.

#### 亮点评价

引用论文在RF-based sound eavesdropping相关工作部分指出，目标论文可以通过在物体上附着无源RFID标签实现穿墙声音窃听。

#### 评价理由

正文引用了[37]，明确提到通过RFID标签实现穿墙声音窃听，说明目标论文的能力被引用论文认可。但该描述是概括性的，未涉及亚毫米级精度或具体方法细节，属于ordinary_reference类型，但具有capability_recognition性质。

### 43. 能力佐证

**引用论文：** Hiding an Ear in Plain Sight: On the Practicality and Implications of Acoustic Eavesdropping with Telecom Fiber Optic Cables  
**被引用论文：** Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration  
**建议：** 候选复核  
**置信度：** high  

#### 原文证据

> Radio Frequency Identification (RFID) **[95]**, or by collecting RF emanations from a microphone [96].

#### 对应参考文献（引用论文原文 References 中的条目）

> **[95]** C. Wang, L. Xie, Y . Lin, W. Wang, Y . Chen, Y . Bu, K. Zhang, and S. Lu,
> “Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing
> **Sub-mm Level Vibration**,”Proceedings of the ACM on Interactive,
> Mobile, Wearable and Ubiquitous Technologies, vol. 5, no. 4, pp. 1–25,
> 2021.

#### 原文上下文

> RF.Wi-Fi signals, for example, have been utilized to profile mouth movements [85] and detect loudspeakers’ vibrations [86], where the distance between the sound source and the signal transmitter is around 2 m and the accuracy is above 0.8. More recent work has focused on millimeter-wave (mmWave) radar [87], [88], [89], [90], [91], [92], [93], [94], Radio Frequency Identification (RFID) **[95]**, or by collecting RF emanations from a microphone [96]. Across these studies, the average source-to-attacker distance is about 3.6 m, with some systems reaching up to 8 m [88], [92]. The accuracy of the speech recognition can be as high as 0.94 at 1 m **[95]** or WER = 0.06 at 2 m [96].

#### 亮点评价

引用论文将目标论文作为RFID声学窃听的代表性工作，并引用其1米距离语音识别准确率达0.94的性能数据，认可其高精度能力。

#### 评价理由

正文明确提到RFID [95]并引用目标论文作为RFID窃听的代表性工作，同时引用了其1米处准确率0.94的性能数据，说明目标论文被认可具有高精度语音识别能力。但未明确提及亚毫米级振动感知，因此判定为capability_recognition而非submm_precision_claim。

### 44. rfid_loudspeaker_vibration

**引用论文：** OISMic: Acoustic Eavesdropping Exploiting Sound-induced OIS Vibrations in Smartphones  
**被引用论文：** Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration  
**建议：** 候选复核  
**置信度：** high  

#### 原文证据

> For instance, Wei et al. [14] inspects subtle disturbances on a target loudspeaker and recovers the audio signal by analyzing the received signal strength (RSS) readings of WiFi packets. Moreover, researchers also use **RFID tags** **[15]** and mmWave radar [16] to detect reﬂected vibration signals for eavesdropping.

#### 对应参考文献（引用论文原文 References 中的条目）

> **[15]** 未解析到引用论文原文 References 条目

#### 原文上下文

> Wireless-based. Wireless-based approaches spy on voice information by analyzing wireless signals reflected from vibrating objects. For instance, Wei et al. [14] inspects subtle disturbances on a target loudspeaker and recovers the audio signal by analyzing the received signal strength (RSS) readings of WiFi packets. Moreover, researchers also use **RFID tags** **[15]** and mmWave radar [16] to detect reflected vibration signals for eavesdropping.

#### 亮点评价

引用论文在相关工作部分将目标论文列为基于RFID的无线窃听方法之一，未突出其亚毫米级振动感知能力。

#### 评价理由

引用属于无线窃听方法的普通相关工作总结，仅提及RFID tags [15]，未具体描述目标论文的亚毫米级精度或能力，属于ordinary_reference；建议review。

### 45. 普通相关工作

**引用论文：** RFNOID: Protecting RFID Motion Privacy via Metasurface  
**被引用论文：** Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration  
**建议：** 候选复核  
**置信度：** medium  

#### 原文证据

> Numerous studies have shown successful attempts in through-wall human motion [3–5] and speech eavesdropping [15–18] via **RFID tags** for adversarial uses.

#### 对应参考文献（引用论文原文 References 中的条目）

> **[15]** C. Wang, L. Xie, Y . Lin, W. Wang, Y . Chen, Y . Bu, K. Zhang, and S. Lu,
> “Thru-the-wall eavesdropping on loudspeakers via rfid by capturing **sub-
> mm level vibration**,” Proc. of ACM IMWUT , 2021.

#### 原文上下文

> Numerous studies have shown successful attempts in through-wall human motion [3–5] and speech eavesdropping [15–18] via **RFID tags** for adversarial uses.

#### 亮点评价

引用论文在引言中列举了多项穿墙RFID窃听研究，其中包括目标论文。

#### 评价理由

引言中目标论文 [15] 被列入一个分组引用列表中，作为多项穿墙窃听研究之一。虽然目标论文确实属于这类研究，但此处仅为列举，没有对目标论文进行单独描述或评价。因此归类为 ordinary_reference，推荐 review 而非 include。

### 46. 穿墙窃听能力佐证

**引用论文：** Rf sensing security and malicious exploitation: A comprehensive survey  
**被引用论文：** Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration  
**建议：** 候选复核  
**置信度：** high  

#### 原文证据

> Similarly, Wang et al. **[102]** proposed Tag-Bug, a **through-wall eavesdropping** system based on **RFID tags** that **reconstructs audio** by capturing **vibrations from loudspeakers**. This approach attaches **RFID tags** to various everyday objects

#### 对应参考文献（引用论文原文 References 中的条目）

> **[102]** C. Wang, L. Xie, Y . Lin, W. Wang, Y . Chen, Y . Bu, K. Zhang,
> and S. Lu, “Thru-the-wall eavesdropping on loudspeakers via RFID
> by capturing **sub-mm level vibration**,” Proceedings of the ACM on
> Interactive, Mobile, Wearable and Ubiquitous Technologies , vol. 5,
> no. 4, pp. 1–25, 2021.

#### 原文上下文

> Shifting the focus of attacks to eavesdropping on audio emitted by loudspeakers, UWHear [101] proposed using sub-10 GHz band IR-UWB radar for non-contact acoustic eavesdropping. ... Similarly, Wang et al. **[102]** proposed Tag-Bug, a **through-wall eavesdropping** system based on **RFID tags** that **reconstructs audio** by capturing **vibrations from loudspeakers**. This approach attaches **RFID tags** to various everyday objects

#### 亮点评价

该调查将Tag-Bug作为基于RFID的穿墙扬声器振动窃听系统进行介绍，肯定了其通过RFID标签捕获振动并重建音频的能力。

#### 评价理由

引文正文描述了目标论文的功能（通过RFID标签捕获扬声器振动实现穿墙窃听），但未明确提到亚毫米级精度，属于能力认可而非直接亚毫米精度声明。尽管目标论文标题包含'Sub-mm Level Vibration'，但正文引用并未复述该精度表述，因此按capability_recognition处理，建议review。

### 47. 穿墙窃听能力佐证

**引用论文：** A Comprehensive Survey of Side-Channel Sound-Sensing Methods  
**被引用论文：** Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration  
**建议：** 候选复核  
**置信度：** high  

#### 原文证据

> **Through-wall eavesdropping** has been demonstrated utilizing various techniques such as...RFID **[23]**...

#### 对应参考文献（引用论文原文 References 中的条目）

> **[23]** 未解析到引用论文原文 References 条目

#### 原文上下文

> **Through-wall eavesdropping** has been demonstrated utilizing various techniques such as laser Doppler vibrometry (LDV) [5], millimeter-wave (mmWave) radar [6], [7], visual sensing [8], WiFi [9]–[11], RFID **[23]**, and other modalities [24].

#### 亮点评价

该综述在介绍穿墙窃听技术时，将目标论文列为基于RFID的代表性工作之一。

#### 评价理由

引用出现在介绍through-wall eavesdropping技术的列举句中，仅作为RFID技术的代表之一，没有描述目标论文的具体能力或亚毫米级精度，属于普通相关工作中；目标引用标记[23]正确引用目标论文。

### 48. 能力佐证

**引用论文：** Hiding an Ear in Plain Sight: On the Practicality and Implications of Acoustic Eavesdropping with Telecom Fiber Optic Cables  
**被引用论文：** Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration  
**建议：** 候选复核  
**置信度：** medium  

#### 原文证据

> - RF.Wi-Fi signals, for example, have been utilized to profile mouth movements [85] and detect loudspeakers’ vibrations [86], where the distance between the sound source and the signal transmitter is around 2 m and the accuracy is above 0.8. More recent work has focused on millimeter-wave (mmWave) radar [87], [88], [89], [90], [91], [92], [93], [94], Radio Frequency Identification (RFID) **[95]**, or by collecting RF emanations from a microphone [96].

#### 对应参考文献（引用论文原文 References 中的条目）

> **[95]** C. Wang, L. Xie, Y . Lin, W. Wang, Y . Chen, Y . Bu, K. Zhang, and S. Lu,
> “Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing
> **Sub-mm Level Vibration**,”Proceedings of the ACM on Interactive,
> Mobile, Wearable and Ubiquitous Technologies, vol. 5, no. 4, pp. 1–25,
> 2021.

#### 原文上下文

> RF.Wi-Fi signals, for example, have been utilized to profile mouth movements [85] and detect loudspeakers’ vibrations [86], where the distance between the sound source and the signal transmitter is around 2 m and the accuracy is above 0.8. More recent work has focused on millimeter-wave (mmWave) radar [87], [88], [89], [90], [91], [92], [93], [94], Radio Frequency Identification (RFID) **[95]**, or by collecting RF emanations from a microphone [96].

#### 亮点评价

引用论文在RF侧信道窃听相关工作部分，将目标论文列为通过RFID实现声学窃听的代表性工作。

#### 评价理由

正文明确将[95]列为RFID领域的最新窃听工作，且前文引用中已明确RFID用于检测扬声器振动，此处列举[95]作为RFID窃听的代表，属于对目标论文能力的认可。虽然属相关工作列举，但结合前文[86]的扬声器振动检测和[95]的标题（含sub-mm），可以认为此处间接确认了RFID窃听能力，属于普通认可，非直接亚毫米精度声明。 成组引用没有单独描述目标论文，需进入候选复核。

### 49. 穿墙窃听能力佐证

**引用论文：** A Batteryless Wireless Microphone Using RF Backscatter  
**被引用论文：** Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration  
**建议：** 候选复核  
**置信度：** high  

#### 原文证据

> Other popular approach is radar-based sound Sensing. Systems like RadioMic [20, 21], Radio2Speech [54], mmspy [3], mmecho [11], RFMic-Phone [32], and others [7–9, 38–40, 43–45, 49] use mmWave radar to detect minute vibrations caused by sound waves. They can offer capabilities like through-wall sensing **[41]** and noise resilience [23, 25], sometimes combining radar with traditional microphones [32].

#### 对应参考文献（引用论文原文 References 中的条目）

> **[41]** Chuyu Wang, Lei Xie, Yuancan Lin, Wei Wang, Yingying Chen, Yanling Bu, Kai Zhang, and Sanglu Lu. 2021. Thru-the-wall eavesdropping
> on loudspeakers via RFID by capturing **sub-mm level vibration**.Proceedings of the ACM on Interactive, Mobile, Wearable and Ubiquitous
> Technologies5, 4 (2021), 1–25.

#### 原文上下文

> In Section 6.2 Non-backscatter RF-based Sound Sensing, the paper describes various radar-based sound sensing systems and mentions 'through-wall sensing' citing **[41]** (the target paper). The context is a general survey of non-backscatter RF approaches, not specifically endorsing the target paper's sub-mm or RFID capability.

#### 亮点评价

该引用论文在非背散射RF声学传感部分，将目标论文作为具备穿墙感知能力的系统之一进行列举，但未展开描述其RFID亚毫米级振动感知特性。

#### 评价理由

引用论文仅在列举雷达声学传感系统时，通过关联引用[41]提及了穿墙感知能力，但未明确区分目标论文是RFID而非雷达，且未提及sub-mm或振动感知细节，属于普通的相关工作罗列，不构成对目标论文的亚毫米级能力认可。

## 五、局限性反馈 / 不宜作为亮点

### 50. 普通相关工作

**引用论文：** mmEcho: A mmWave-based Acoustic Eavesdropping Method  
**被引用论文：** Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration  
**建议：** 候选复核  
**置信度：** high  

#### 原文证据

> **[21]** relies on **RFID tags** in combination with cGAN for acoustic eavesdropping. However, it needs to pre-install **RFID tags** in the victim’s proximity, which reduces its practicality.

#### 对应参考文献（引用论文原文 References 中的条目）

> **[21]** C. Wang, L. Xie, Y . Lin, W. Wang, Y . Chen, Y . Bu, K. Zhang,
> and S. Lu, “Thru-the-wall eavesdropping on loudspeakers via rfid
> by capturing **sub-mm level vibration**,” Proc. of ACM on Interactive,
> Mobile, Wearable and Ubiquitous Technologies (IMWUT , vol. 5,
> no. 4, pp. 1–25, 2021.

#### 原文上下文

> RF-based acoustic eavesdropping. ... **[21]** relies on **RFID tags** in combination with cGAN for acoustic eavesdropping. However, it needs to pre-install **RFID tags** in the victim’s proximity, which reduces its practicality.

#### 亮点评价

引用论文将目标论文归类为基于RF的窃听相关工作，指出其使用RFID标签与cGAN结合进行声学窃听，但需在受害者附近预装标签，降低了实用性。未提及亚毫米级精度或首次贡献。

#### 评价理由

该处为普通相关工作提及，并指出了局限性（需预装标签），未明确肯定其亚毫米精度或首次性。

### 51. 局限性反馈

**引用论文：** Radsee: See your handwriting through walls using fmcw radar  
**被引用论文：** Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration  
**建议：** 候选复核  
**置信度：** high  

#### 原文证据

> **RFID tag** can also be used to measure the vibration pattern of a loudspeaker **[44]**.

#### 对应参考文献（引用论文原文 References 中的条目）

> **[44]** C. Wang, L. Xie, Y . Lin, W. Wang, Y . Chen, Y . Bu, K. Zhang, and S. Lu,
> “Thru-the-wall eavesdropping on loudspeakers via rfid by capturing **sub-
> mm level vibration**,” Proceedings of the ACM on Interactive, Mobile,
> Wearable and Ubiquitous Technologies, vol. 5, no. 4, pp. 1–25, 2021.
> 16

#### 原文上下文

> Through-Wall Detection using RFID. ... **RFID tag** can also be used to measure the vibration pattern of a loudspeaker **[44]**. But, due to its long wavelength (33 cm), it is not a good candidate for tracking mm-level movements.

#### 亮点评价

引用论文指出RFID标签可测量扬声器振动模式（引用目标论文），但认为RFID因波长较长不适合毫米级运动跟踪。

#### 评价理由

正文仅提及RFID标签可测量扬声器振动，并引用目标论文，但随后指出RFID由于波长较长不适合毫米级运动跟踪，属于普通相关工作且含负面评价。

### 52. 局限性反馈

**引用论文：** Towards Unconstrained Vocabulary Eavesdropping With mmWave Radar Using GAN  
**被引用论文：** Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration  
**建议：** 候选复核  
**置信度：** high  

#### 原文证据

> Akin to WiFi works, RFID **[15]** and Doppler radar [19] have been leveraged for eavesdropping. In particular, **[15]** requires a pre-installed tag in the victim’s room.

#### 对应参考文献（引用论文原文 References 中的条目）

> **[15]** C. Wang et al., “Thru-the-wall eavesdropping on loudspeakers
> via RFID by capturing **sub-mm level vibration**,” Proc. ACM Inter-
> active, Mobile, Wearable Ubiquitous Technol., vol. 5, no. 4, pp. 1–25,
> 2021.

#### 原文上下文

> Akin to WiFi works, RFID **[15]** and Doppler radar [19] have been leveraged for eavesdropping. In particular, **[15]** requires a pre-installed tag in the victim’s room. Compared to our approach, these works relying on low resolution traffic data due to lower frequencies and packet rates. Also, they require a multi-antenna setup to localize victims and thus result in larger physical footprint compared to mmWave, making the attack more difficult to be carried out in practice.

#### 亮点评价

相关工作将目标RFID论文列为利用低分辨率无线信号进行窃听的工作，并指出其实践限制。

#### 评价理由

正文将[15]作为RFID窃听的例子，并指其需要预装标签和低分辨率局限性。属于普通相关工作列举，未明确确认亚毫米级能力。

### 53. 局限性反馈

**引用论文：** TWLip: Exploring Through-Wall Word-Level Lip Reading Based on Coherent SISO Radar  
**被引用论文：** Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration  
**建议：** 候选复核  
**置信度：** medium  

#### 原文证据

> Most related studies utilized millimeter waves to penetrate low-loss wall materials (such as wood, glass, and soundproofing materials) to directly or indirectly detect the content played in speakers behind walls **[18]**, [19], [20] rather than the lip movements.

#### 对应参考文献（引用论文原文 References 中的条目）

> **[18]** 未解析到引用论文原文 References 条目

#### 原文上下文

> Research on through-wall lip-reading recognition is limited; Khanna et al. [3] achieved a high accuracy of 94% in classifying 26 letters using Doppler radar to penetrate a 0.6 cm thick wooden board by employing deep CNNs. Most related studies utilized millimeter waves to penetrate low-loss wall materials (such as wood, glass, and soundproofing materials) to directly or indirectly detect the content played in speakers behind walls **[18]**, [19], [20] rather than the lip movements.

#### 亮点评价

论文将文献[18]列为利用毫米波穿墙检测扬声器内容的代表性研究，认可其穿墙侦听能力。

#### 评价理由

句子明确将[18]归类为通过毫米波穿透低损耗墙壁检测扬声器内容的代表性工作，承认了其穿墙侦听能力。 无法从引用论文 References 中解析该编号对应的原始条目，不能推荐纳入。

### 54. 局限性反馈

**引用论文：** Acoustic Eavesdropping From Sound-Induced Vibrations With Multi-Antenna mmWave Radar  
**被引用论文：** Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration  
**建议：** 候选复核  
**置信度：** medium  

#### 原文证据

> **[23]** utilizes **RFID tags** and cGAN to perform acoustic eavesdropping, but this approach is less practical as it requires pre-installing **RFID tags** near the target.

#### 对应参考文献（引用论文原文 References 中的条目）

> **[23]** C. Wang et al., “Thru-the-wall eavesdropping on loudspeakers via RFID
> by capturing **sub-mm level vibration**,” inProc. ACM Interactive Mobile
> Wearable Ubiquitous Technol., vol. 5, no. 4, pp. 1–25, 2021.

#### 原文上下文

> Similarly, [22] employs the same wireless-based technology to capture audio with frequencies below 400 Hz. These methods cannot recover human speech due to the low frequency response.**[23]** utilizes **RFID tags** and cGAN to perform acoustic eavesdropping, but this approach is less practical as it requires pre-installing **RFID tags** near the target. Overall, these methods based on WiFi signals and impulse radio [14], [15], [21], [22], **[23]** are limited by the inadequate vibration resolution caused by low packet rates and long wavelengths.

#### 亮点评价

引文[23]被提及使用RFID标签和cGAN进行声学窃听，但被评价为需预装标签、实用性较低。

#### 评价理由

正文明确使用标记[23]提及目标论文的方法（RFID+cGAN窃听），属于具体的方法使用描述。虽包含负面评价，但确实描述了该方法，符合method_use。 原文或评价理由包含局限性/实用性不足表述，不能作为推荐纳入的正向强证据。

### 55. 局限性反馈

**引用论文：** PowerEar: An Audio Eavesdropping Attack on Mobile Devices Through USB Power Side Channel  
**被引用论文：** Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration  
**建议：** 候选复核  
**置信度：** high  

#### 原文证据

> Reference **[50]** proposes an RFID-based acoustic eavesdropping method that utilizes **RFID tags** near the target user. These methods **[50]**, [51], [53], [54] suffer from insufficient vibration resolution due to the long wavelength and low packet rate.

#### 对应参考文献（引用论文原文 References 中的条目）

> **[50]** C. Wang et al., “Thru-the-wall eavesdropping on loudspeakers via RFID
> by capturing **sub-mm level vibration**,” in Proc. ACM IMWUT, vol. 5,
> 2021, pp. 1–25.

#### 原文上下文

> In recent years, researchers have exploited RF technologies (e.g., WiFi, RFID, mmWave) to perform eavesdropping attacks. ... Reference **[50]** proposes an RFID-based acoustic eavesdropping method that utilizes **RFID tags** near the target user. These methods **[50]**, [51], [53], [54] suffer from insufficient vibration resolution due to the long wavelength and low packet rate.

#### 亮点评价

引用论文将目标论文列为RFID声学窃听方法，但同时指出其振动分辨率不足。

#### 评价理由

本段将[50]作为RFID声学窃听方法之一进行引用，但紧接着指出包括[50]在内的几种方法存在振动分辨率不足的局限性。虽然提及了RFID和振动，但未明确认可其亚毫米级精度，且包含负面评价，因此属于ordinary_reference，推荐review。

### 56. 局限性反馈

**引用论文：** PowerEar: An Audio Eavesdropping Attack on Mobile Devices Through USB Power Side Channel  
**被引用论文：** Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration  
**建议：** 候选复核  
**置信度：** high  

#### 原文证据

> Reference **[50]** proposes an RFID-based acoustic eavesdropping method that utilizes **RFID tags** near the target user.

#### 对应参考文献（引用论文原文 References 中的条目）

> **[50]** C. Wang et al., “Thru-the-wall eavesdropping on loudspeakers via RFID
> by capturing **sub-mm level vibration**,” in Proc. ACM IMWUT, vol. 5,
> 2021, pp. 1–25.

#### 原文上下文

> In recent years, researchers have exploited RF technologies (e.g., WiFi, RFID, mmWave) to perform eavesdropping attacks. ... Reference **[50]** proposes an RFID-based acoustic eavesdropping method that utilizes **RFID tags** near the target user. These methods **[50]**, [51], [53], [54] suffer from insufficient vibration resolution due to the long wavelength and low packet rate.

#### 亮点评价

该论文在背景介绍中将目标论文列为一种基于RFID的声学窃听方法，但未对其亚毫米级精度或首次性做明确认可。

#### 评价理由

引用论文仅在相关工作段落中顺带提及目标论文，属于普通相关文献列举，且随后的句子将[50]与其他方法一起批评振动分辨率不足。

### 57. 局限性反馈

**引用论文：** mmOrbit: Micrometer-Level Vibration and Rotor Orbit Measurement via Synchronized Dual mmWave Radars  
**被引用论文：** Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration  
**建议：** 候选复核  
**置信度：** high  

#### 原文证据

> The accuracy of longer wavelength RF signals (e.g., RFID**[19]**, WiFi[20]) is limited.

#### 对应参考文献（引用论文原文 References 中的条目）

> **[19]** C. Wang et al., “Thru-the-wall eavesdropping on loudspeakers via RFID
> by capturing **sub-mm level vibration**,”Proc. ACM Interactive, Mobile,
> Wearable Ubiquitous Technol., vol. 5, no. 4, pp. 1–25, 2021.

#### 原文上下文

> However, in the scenario of micron mechanical vibration, the accuracy of longer wavelength RF signals (e.g., RFID**[19]**, WiFi[20]) is limited. The mmWave is a better choice for micro-vibration scenarios with its smaller wavelength.

#### 亮点评价

本文在微机械振动场景下指出，较长波长RF信号（如RFID[19]）的精度有限，以此说明选择毫米波雷达的合理性。

#### 评价理由

引用论文将目标论文作为RFID代表性工作提及，但仅指出其精度受限，未确认或描述其亚毫米级能力，属于普通相关文献对比，不满足submm_precision_claim或capability_recognition的严格证据要求。

### 58. 局限性反馈

**引用论文：** Radsee: See your handwriting through walls using fmcw radar  
**被引用论文：** Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration  
**建议：** 候选复核  
**置信度：** high  

#### 原文证据

> **RFID tag** can also be used to measure the vibration pattern of a loudspeaker **[44]**. But, due to its long wavelength (33 cm), it is not a good candidate for tracking mm-level movements.

#### 对应参考文献（引用论文原文 References 中的条目）

> **[44]** C. Wang, L. Xie, Y . Lin, W. Wang, Y . Chen, Y . Bu, K. Zhang, and S. Lu,
> “Thru-the-wall eavesdropping on loudspeakers via rfid by capturing **sub-
> mm level vibration**,” Proceedings of the ACM on Interactive, Mobile,
> Wearable and Ubiquitous Technologies, vol. 5, no. 4, pp. 1–25, 2021.
> 16

#### 原文上下文

> Through-Wall Detection using RFID. Through-wall detection is also possible by using RFID systems. Tadar [59] and RF-HMS [51] demonstrated their capabilities of tracking human moving directions through walls using an array of **RFID tags**. However, the tracking error in these systems is around 10 cm, indicating their incapability of tracking mm-level hand movements. **RFID tag** can also be used to measure the vibration pattern of a loudspeaker **[44]**. But, due to its long wavelength (33 cm), it is not a good candidate for tracking mm-level movements.

#### 亮点评价

引用论文在相关工作中提到目标论文使用RFID通过捕捉亚毫米级振动实现穿墙扬声器窃听，但指出其波长限制，未作为亚毫米级感知能力的直接证据。

#### 评价理由

正文引用[44]说明RFID标签可用于测量扬声器振动模式，但紧接着指出由于波长较长不适合毫米级运动追踪。该引用属于普通相关文献列举，未明确确认目标论文的亚毫米级能力，反而指出其局限性。

### 59. 局限性反馈

**引用论文：** mmOrbit: Micrometer-Level Vibration and Rotor Orbit Measurement via Synchronized Dual mmWave Radars  
**被引用论文：** Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration  
**建议：** 候选复核  
**置信度：** high  

#### 原文证据

> The mmWave naturally supports much more fine-grained sensing, compared with other wireless technologies (i.e., RFID [10], WiFi [11], UWB [12]). ... However, in the micron-level vibration scenario, mmWave-based micro-displacement and rotor orbit measurements encounter several challenges... The accuracy of longer wavelength RF signals (e.g., RFID **[19]**, WiFi [20]) is limited.

#### 对应参考文献（引用论文原文 References 中的条目）

> **[19]** C. Wang et al., “Thru-the-wall eavesdropping on loudspeakers via RFID
> by capturing **sub-mm level vibration**,”Proc. ACM Interactive, Mobile,
> Wearable Ubiquitous Technol., vol. 5, no. 4, pp. 1–25, 2021.

#### 原文上下文

> The mmWave naturally supports much more fine-grained sensing, compared with other wireless technologies (i.e., RFID [10], WiFi [11], UWB [12]). ... However, in the micron-level vibration scenario, mmWave-based micro-displacement and rotor orbit measurements encounter several challenges... Displacement is also an essential parameter of mechanical vibration. However, in the scenario of micron mechanical vibration, the accuracy of longer wavelength RF signals (e.g., RFID **[19]**, WiFi [20]) is limited.

#### 亮点评价

该论文在相关工作中将目标论文列为RFID振动感知的普通参考，未突出其亚毫米级精度或穿墙窃听能力。

#### 评价理由

目标论文在正文中被列为RFID的代表性工作，但上下文是在普通比较不同无线技术的感知能力，且指出RFID精度有限，属于普通相关文献列举，未特别强调亚毫米或穿墙能力。

### 60. 普通相关工作

**引用论文：** Radsee: See your handwriting through walls using fmcw radar  
**被引用论文：** Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration  
**建议：** 候选复核  
**置信度：** medium  

#### 原文证据

> **Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration**

#### 对应参考文献（引用论文原文 References 中的条目）

> **[44]** C. Wang, L. Xie, Y . Lin, W. Wang, Y . Chen, Y . Bu, K. Zhang, and S. Lu,
> “Thru-the-wall eavesdropping on loudspeakers via rfid by capturing **sub-
> mm level vibration**,” Proceedings of the ACM on Interactive, Mobile,
> Wearable and Ubiquitous Technologies, vol. 5, no. 4, pp. 1–25, 2021.
> 16

#### 原文上下文

> Reference **[44]** is the target paper title: '**Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration**'.

#### 亮点评价

目标论文标题明确提及'Sub-mm Level Vibration'，但引用正文未对亚毫米精度进行显式描述或确认。

#### 评价理由

目标论文标题包含'Sub-mm Level Vibration'，但引用正文中未显式提及'sub-mm'或'millimeter-level'等词；标题本身可作为亚毫米级声明的间接证据，但引用正文未锚定，因此归为'include'而非高置信度。 证据仅来自题名、参考文献条目或标题列举，不是正文第三方评价。

### 61. 普通相关工作

**引用论文：** mmHSE: Enhanced Eavesdropping Attack on Headsets Leveraging COTS mmWave Radar  
**被引用论文：** Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing Sub-mm Level Vibration  
**建议：** 候选复核  
**置信度：** medium  

#### 原文证据

> COTS **RFID tags** **[37]**

#### 对应参考文献（引用论文原文 References 中的条目）

> **[37]** Chuyu Wang, Lei Xie, Yuancan Lin, Wei Wang, Yingying Chen, Yanling Bu, Kai Zhang, and Sanglu Lu. 2022. Thru-the-wall Eavesdropping
> on Loudspeakers via RFID by Capturing **Sub-mm Level Vibration**. Proc. ACM Interact. Mob. Wearable Ubiquitous Technol. 5, 4, Article 182
> (Dec. 2022), 25 pages. doi:**10.1145/3494975**

#### 原文上下文

> Alternative signals also offer intriguing solutions for audio perception, such as accelerometer signal in smartphone [1, 14, 19], mechanical signals in magnetic hard disks [17], smartphone camera image stream signals [22], COTS **RFID tags** **[37]** and so on.

#### 亮点评价

该文将目标论文列为基于COTS RFID标签的音频感知方法之一，未展开讨论。

#### 评价理由

引用仅为列举性提及，无详细描述或评价，属于普通相关引用。 证据仅来自题名、参考文献条目或标题列举，不是正文第三方评价。

## 六、不纳入证据摘要

本次分析中有 196 条证据被模型建议不纳入正式报告。
