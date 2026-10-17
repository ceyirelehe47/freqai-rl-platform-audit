# DESIGN_NOTE — 持续方向辅助保持对照(2026-10-17 v2;PLAN_ONLY)

> v2(审查方 4966):λ=1 为**未验证候选**;每 minibatch
> 同一总 loss 求一次 aux·**不额外 optimizer.step**;
> 1536 批固定 4 输入;**新臂可审计 post_aux 边界**
> (不称与旧 a2 严格同边界);面板 6 点固定;剂量/共享
> 隐层/全局 clipping 混淆明示;新边界保存/回读零污染;
> 开销在原预算内;完成或失败即停;不扫 λ。

## 一、目标与机制(单臂;双对照=B32 现成/a2 现成)
- 总 loss = 原 PPO 损失 + λ·aux,λ=1.0(**未验证候选**,
  无成功先验,不扫);
- aux=mean(relu(.05−y·m)²),y=sign(s·q·c) 可见标签,
  m=条件 REBAL 均值(同一真实 raw8 链);
- **干预时点**:预教学 256 批 + PPO 阶段**每 optimizer
  minibatch 在同一总 loss 中求一次 aux**——**不额外
  optimizer.step**(无独立辅助优化器步);
- 批计量:**1280 PPO minibatch + 256 预教学=1536 批**,
  均为固定 4 输入;**320 是 epoch 更新轮数,
  不是 optimizer 步数**(每轮 4 minibatch)。

## 二、混淆明示(不归因越界)
1. **持续项也增加监督剂量**(1536 vs a2 的 256)——
   不能排除剂量而只归因时点;机制解释保持"未证"。
2. **共享 actor 隐层/全局 clipping**:辅助梯度经共享
   隐层与 PPO clip 可**间接影响 branch/critic**——
   卡/报告须分列 branch(开仓)与 critic 侧指标,
   不得称"只动条件均值"。

## 三、边界与新臂审计
- **新臂可审计 post_aux 边界**:预教学后立即保存
  checkpoint_post_aux.zip+param digest+Adam 空态核+
  四 RNG/_last_obs/_last_episode_starts 快照;**不称
  与旧 a2 严格同边界**(a2 无该档;仅同初态同规程)。
- 边界保存与回读:**不得污染 RNG/Adam/episode 状态**
  (保存用 no_grad 序列化;回读后核四 RNG 与 episode
  标志与保存点逐位一致才继续)。
- **全部新增开销(过程面板快照/边界档)在原预算内**
  (900wall/600CPU/1GiB·34880 经济步不增;面板快照
  零 env 步)。

## 四、面板与指标
- **面板固定 6 点:pre_aux/post_aux 及 8192/16384/
  24576/32768(末次即 final)**——共 **6×8 行/6 batch**,
  不多不少;
- **q=0.75 不在 panel 8 行**(panel 含 q1/.5/.25)——
  **不得称全部训练点均测**(训练辅助输入含 q.75,
  面板观测不含);
- 报告分列:**方向符号响应/未监督 q 响应/公开分布
  (P_H·mode)/实际开仓(H32·H1 根数)/H1 成本**;
  收益仅描述性比较(配对差+SE),不作毕业判据。

## 五、停止条件
完成或失败即停;不扫 λ/不加步/不换 seed;
course_gate=not_frozen。

## 六、不做
本件 PLAN_ONLY:不实现新臂/不训练/不 forward;
不改五源;不 stage/commit/push。
