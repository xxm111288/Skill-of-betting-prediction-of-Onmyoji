#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
阴阳师「对弈竞猜」蒙特卡洛模拟器（启发式 / 比较型，非真值引擎）

定位：把知识库里的公式与机制落到一个可复现的随机模拟里，输出**双方胜率的相对排序**
      与**敏感性**（哪个参数一动就翻盘）。它不是官方引擎，绝对值不可当真，趋势与
      敏感性可用。所有建模假设写在 ASSUMPTIONS 里，并在输出中一并打印。

用法（跨平台，仅需 Python 3.10+ 标准库，无第三方依赖）：

  python3 simulate_duel.py lineup.json --trials 20000 --out result.json --sensitivity
  # Windows 上把 python3 换成 python 即可
  # 参数：--trials(默认20000) --seed --out --sensitivity --log

输出会写入 --out 指定的 JSON 文件（同时也会打印一份摘要到 stdout）。
若所在 shell 不回显 stdout，直接用 Read 工具读该文件即可。

lineup.json 的 schema 与示例见 ../assets/lineup_template.json
机制口径与假设见 ../kb/01_玩法与预测框架.md、../kb/02_核心数值与公式.md、../kb/05_御魂与套装.md
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import statistics
import sys

# ----------------------------------------------------------------------------
# ASSUMPTIONS —— 所有建模假设集中在此，输出时会打印，便于人工裁定
# ----------------------------------------------------------------------------
ASSUMPTIONS = [
    "伤害走知识库公式：总攻击×技能系数×暴击修正×300/(300+防御)×增伤区×减伤区×御魂修正。",
    "命中两段判定：命中率=基础概率×(1+效果命中)，封顶100%/下限1%；再÷(1+效果抵抗)。",
    "多段控制按 1-(1-p)^n 独立判定。",
    "治疗与护盾吃暴击暴伤；治疗受裁决之力『治疗量 -10%/层』削减。",
    "裁决鬼王每 arbiter_period 个单位回合行动 1 次；每层 增伤+15%、治疗-10%；第 11 次行动起增伤改 +30%/层。",
    "对弈竞猜开局 4 火；火灵 +3（多套只算一套）；座敷先机 +3/只（可叠加）；鬼火上限 8。",
    "鬼火条 5 格，每个己方单位行动结束推 1 格；满格回复 3/4/5/5... 点。",
    "行动条为周长 1 的圆：初始位置 = 自身速度/全场一速；拉条可超 100% 立即行动；推条最低 0%。",
    "群攻目标顺序 4→1→2→3→5（按『阵容序号』）。单体优先打当前生命比例最低的存活敌方。",
    "『打在护盾上的伤害不触发控制类御魂与针女』——本模拟按此实现。",
    "首领御魂共 13 件（荒骷髅/土蜘蛛/胧车/地震鲶/蜃气楼/鬼灵歌伎/夜荒魂 + 原星痕的八咫镜/天羽羽斩/"
    "预言星盘/月之石/纺缘锤/稻荷穗箭）的 2 件套被动在对弈中一律不生效，直接忽略"
    "（原星痕 6 件自 2026-04-15 起已被官方『调整为首领御魂，并不再支持斗技、结界突破、道馆』）。",
    "近似处理（已明确标注）：兵主部按每回合 +1 层（上限 3 层）无视 75 防御；"
    "尘冢按固定 +25%（未实现友方人数差）；贝吹坊按 +25% 攻击（未实现贝甲挡 1 次）；"
    "遗念火按常驻 +40% 抵抗、夜送犬按常驻 +80% 抵抗；纺缘锤已被移出建模（对弈无效）；"
    "元兴寺/应声虫/火之车的减费部分未建模。",
    "平局兜底：存活数多者胜 → 再比存活者剩余生命总和。",
    "本模拟不建模：传导伤害、召唤物、多形态切换、协战、回合外触发的精确时序、"
    "以及部分御魂的完整细节（见输出里的『机制未建模』告警）。这些请人工在报告里定性补充。",
]

# 首领御魂：2 件套被动仅在对怪物战斗时生效 → 对弈无效（知识库 05 §1.2 / §3）
# 「原星痕御魂」6 件：2026-04-15 官方维护后【已调整为首领御魂】，且明确
# 「不再支持斗技 / 结界突破 / 道馆玩法」→ 对弈竞猜（自动斗技）同样不生效。
# ⚠️ 网上流传的「星痕御魂 PVP 生效」是 2025-03 体验服状态，已作废（见 05 §2.7b）。
ARENA_DISABLED_SOULS = {
    # 首领御魂（逢魔系列）
    "荒骷髅", "土蜘蛛", "胧车", "地震鲶", "蜃气楼", "鬼灵歌伎", "夜荒魂",
    # 原星痕御魂（2026-04-15 起为首领御魂，PVP 不生效）
    "八咫镜", "天羽羽斩", "预言星盘", "月之石", "纺缘锤", "稻荷穗箭",
}

# 官方御魂名单全量 70 个（来源：g37simulator get_equip_list，2026-09-24 抓取）
# 作用：区分「官方存在但本模拟未建模」与「名字写错了」。名单见 05A_御魂全量.md。
ALL_SOUL_NAMES = {
    "三味", "伤魂鸟", "元兴寺", "八咫镜", "共潜", "兵主部", "出世螺", "反枕", "叠叩",
    "土蜘蛛", "地藏像", "地震鲶", "夜啼石", "夜荒魂", "夜送犬", "天羽羽斩", "奉海图",
    "尘冢", "幽谷响", "应声虫", "心眼", "恶楼", "招财猫", "无刀取", "日女巳时",
    "月之石", "木魅", "树妖", "油赤子", "海月火玉", "涂佛", "涅槃之火", "火之车",
    "火灵", "片叶之苇", "狂骨", "狰", "珍珠", "破势", "稻荷穗箭", "纺缘锤", "网切",
    "胧车", "荒骷髅", "薙魂", "蚌精", "蜃气楼", "蝠翼", "被服", "贝吹坊", "轮入道",
    "返魂香", "遗念火", "针女", "钓瓶火", "钟灵", "镇墓兽", "镜姬", "阴摩罗", "隐念",
    "雨降", "雪幽魂", "青女房", "预言星盘", "飞缘魔", "骰子鬼", "鬼灵歌伎", "魅妖",
    "魍魉之匣", "鸣屋",
}

# 御魂效果表。数值全部取自知识库 05_御魂与套装.md（含冲突裁定结果）。
SOULS: dict[str, dict] = {
    # --- 攻击加成 ---
    "阴摩罗": {"fire_on_kill": 3},
    "蝠翼": {"lifesteal": 0.20},
    "狰": {"counter": 0.35},
    "轮入道": {"extra_turn": 0.20},
    "心眼": {"dmg_per_missing": (0.15, 0.10)},      # 每降低15%生命 → +10%伤害
    "鸣屋": {"dmg_vs_controlled": 0.45},
    "狂骨": {"dmg_per_fire": 0.08},
    "兵主部": {"ignore_def_stack": (75, 3)},        # 每层无视 75 防御，上限 3 层
    "片叶之苇": {"dmg_if_full_hp": 0.45},           # 满血 +45% 伤害
    "海月火玉": {"extra_fire_dmg": (1, 0.40)},      # 额外耗 1 火 → +40% 伤害
    # --- 暴击加成 ---
    "破势": {"dmg_vs_high_hp": (0.70, 0.40)},
    "针女": {"proc": 0.40, "hp_pct": 0.10, "cap_atk_mult": 1.20},
    "网切": {"ignore_def": (0.50, 0.45)},
    "三味": {"spd_on_control": 30},
    "伤魂鸟": {"dmg_per_death": 0.20, "dmg_per_death_cap": 1.20, "heal_on_death": 0.20},
    "镇墓兽": {"cdmg_per_missing": 0.005},
    "无刀取": {"ramp_dmg": (0.15, 0.45)},           # 回合结束 +15% 永久，上限 45%
    # --- 生命加成 ---
    "被服": {"taken_mult": 0.70},
    "地藏像": {"crit_shield": (1.00, 0.10), "ally_crit_shield_p": 0.30},
    "涅槃之火": {"heal_low_hp": (0.30, 0.15)},
    "镜姬": {"reflect": (0.30, 1.00)},
    "钟灵": {"on_hit_control": ("眩晕", 0.10, "hard"), "if_no_stun": 0.20},
    "树妖": {"heal_mult": 1.20},
    "薙魂": {"share_single": (0.50, 0.50)},
    "夜啼石": {"inherit_on_ally_death": 0.30},      # 友方阵亡获得其 30% 属性
    "叠叩": {"team_crit_taken_mult": (1.20, 0.85)},  # 初始暴击>120% → 全队受暴击伤害 -15%
    "共潜": {"dispel_on_turn": (1, 2)},             # 回合结束驱散 1（未造成伤害则 2）个负面
    "恶楼": {"ramp_after_turns": (8, 0.80, 0.80)},  # 前 8 回合封禁，之后 +80% 增伤/-80% 受伤
    "涂佛": {"team_buff_on_basic": (0.15, 0.15)},   # 普攻/无法动作 → 全队 +15% 抗性与伤害
    "出世螺": {"heal_on_hit": 0.10, "dmg_cap_pct": 0.60},
    "奉海图": {"taken_mult": 0.70},
    "火之车": {"extra_turn_ramp": 4},               # 每 4 回合获得 1 个额外回合
    # --- 防御加成 ---
    "魅妖": {"on_hit_control": ("混乱", 0.25, "soft")},
    "雪幽魂": {"on_hit_control": ("冰冻", 0.15, "soft"), "control_boost_if_slowed": 0.30,
               "slow_attacker": 30},
    "招财猫": {"fire_on_turn": (0.50, 2)},
    "反枕": {"on_hit_control": ("睡眠", 0.25, "soft")},
    "日女巳时": {"push_on_hit": (0.20, 0.30), "push_bonus_if_buffed": 0.10},
    "珍珠": {"heal_gives_shield": 0.30},
    "木魅": {"drain_fire": 0.25},
    # --- 效果命中 ---
    "蚌精": {"team_shield_pct": 0.10, "team_shield_rounds": 1},
    "火灵": {"fire_start": 3, "unique": True},
    "飞缘魔": {},                                    # ⚠️ 效果未核实
    "遗念火": {"res_avg": 40},                       # 近似：平均 2 层念火 × 20% 抵抗
    "油赤子": {"team_def_bonus": 0.16},              # 2 层灵元 × 8% 全队防御
    "贝吹坊": {"atk_mult": 1.25},                    # 贝甲存在时 +25% 攻击
    # --- 效果抵抗 ---
    "魍魉之匣": {"random_control": ["沉默", "眩晕", "混乱", "减疗"], "random_control_p": 0.25},
    "骰子鬼": {"counter_on_resist": True, "spd_on_control": 25},
    "幽谷响": {"reflect_control": 0.50},
    "返魂香": {"on_being_hit_control": ("眩晕", 0.25)},
    "夜送犬": {"res_avg": 80},                       # 近似：首次受控后 +80% 抵抗
    "钓瓶火": {"fire_bar_extra": 1, "heal_lowest_def_pct": 7.00},
}

# 官方名单内、但本模拟**未建模**的御魂效果（会在 warnings 里逐个列出，便于人工补充）
UNMODELED_SOULS = {
    "元兴寺": "唯一效果：造成控制时每命中 1 目标使全队伤害 +5%，上限 +40%，持续 2 回合",
    "应声虫": "携带者获得 20% 协战概率",
    "青女房": "4 件套效果未纳入本次核对",
    "隐念": "4 件套效果未纳入本次核对",
    "雨降": "4 件套效果未纳入本次核对",
    "贝吹坊": "本模拟只按 +25% 攻击处理，未实现「每回合挡 1 次伤害」的贝甲",
    "尘冢": "本模拟按 +25% 固定处理，未实现「每多一个友方 +4%」",
    "兵主部": "本模拟按每回合 +1 层（上限 3 层）近似，层数增长节奏可能不同",
}

CONTROL_KIND = {
    "冰冻": "skip", "沉睡": "skip", "眩晕": "skip", "变形": "skip",
    "沉默": "basic_only", "禁锢": "basic_only",
    "混乱": "random_target", "嘲讽": "taunt", "挑衅": "taunt",
    "减疗": "heal_down",
}
HARD_CONTROLS = {"变形", "眩晕", "挑衅"}
SKIP_CONTROLS = {"冰冻", "沉睡", "眩晕", "变形"}


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


# ----------------------------------------------------------------------------
# Unit
# ----------------------------------------------------------------------------
class Unit:
    def __init__(self, spec: dict, side: str, index: int, warnings: list):
        self.side = side
        self.name = spec.get("name", f"{side}#{index+1}")
        self.pos = int(spec.get("pos", index + 1))          # 1..5 阵容序号
        self.spd = float(spec.get("spd", 100))
        self.base_spd = self.spd
        self.atk = float(spec.get("atk", 3000))
        self.base_atk = self.atk
        self.max_hp = float(spec.get("hp", 12000))
        self.hp = self.max_hp
        self.dfn = float(spec.get("def", 500))
        self.crit = float(spec.get("crit", 100)) / 100.0     # 存百分比
        self.cdmg = float(spec.get("cdmg", 150)) / 100.0
        self.hit = float(spec.get("hit", 0))
        self.res = float(spec.get("res", 0))
        self.role = spec.get("role", "dps")

        # 御魂
        self.souls = list(spec.get("souls", []))
        self.flags: dict = {}
        for s in self.souls:
            if s in ARENA_DISABLED_SOULS:
                warnings.append(f"[对弈无效] {self.name} 携带首领御魂「{s}」——2件套被动在对弈中不生效，已忽略")
                continue
            if s not in SOULS:
                if s in ALL_SOUL_NAMES:
                    warnings.append(
                        f"[机制未建模] {self.name} 携带「{s}」——它是官方御魂，但本模拟尚未实现其效果"
                        f"（文案见 05A_御魂全量.md），已按无效果处理；请在报告『未建模项』里列出")
                else:
                    warnings.append(
                        f"[疑似拼写错误] {self.name} 携带「{s}」——不在官方 70 个御魂名单中，"
                        f"请核对御魂名（名单见 05A_御魂全量.md）")
                continue
            for k, v in SOULS[s].items():
                self.flags[k] = v

        # 被动
        p = spec.get("passive", {}) or {}
        self.revive_left = int(p.get("revive", 0))            # 免死/复活次数
        self.no_heal = bool(p.get("no_heal", False))
        self.passive_reduce = float(p.get("reduce", 0.0))      # 减伤（0.3 = 30%）
        self.start_shield_pct = float(p.get("start_shield_pct", 0.0))
        self.dmg_mult = float(p.get("dmg_mult", 1.0))          # 技能/被动增伤
        self.on_death_effects = p.get("on_death", []) or []

        # —— 由御魂 flags 直接改面板/状态的部分 ——
        if "atk_mult" in self.flags:
            self.atk *= self.flags["atk_mult"]
        if "res_avg" in self.flags:                 # 近似：把「层叠型抵抗」折算为常驻值
            self.res += self.flags["res_avg"]
        if self.flags.get("no_arena_effect"):
            bad = [x for x in self.souls if SOULS.get(x, {}).get("no_arena_effect")]
            warnings.append(
                f"[对弈无效] {self.name} 携带「{'/'.join(bad)}」——该御魂效果作用于「阴阳师」，"
                f"而对弈竞猜没有阴阳师 → 等于空 2 件套（只剩随机固有属性）")
        for sname in self.souls:
            if sname in UNMODELED_SOULS:
                warnings.append(
                    f"[机制未建模] {self.name} 携带「{sname}」——{UNMODELED_SOULS[sname]}；"
                    f"本模拟未实现，请在报告『未建模项』里列出")
        self._cast_bonus = 0.0
        self._taken_mult_1turn = 1.0
        self._bonus_stacks = 0

        # 技能
        self.skills = spec.get("skills", []) or []
        self.fallback_basic = spec.get("basic", {
            "name": "普攻", "cost": 0, "coef": 1.00, "hits": 1, "aoe": False, "cd": 0,
        })

        # 运行时
        self.shield = self.max_hp * self.start_shield_pct
        self.alive = True
        self.controls: list[dict] = []
        self.cds: dict[int, int] = {}
        self.extra_turn = False
        self.turn_count = 0                 # 本式神行动次数（用于控制计时）
        self.kills = 0
        self.deaths_seen = 0

    # -- 状态辅助 --
    @property
    def hp_ratio(self):
        return 0.0 if not self.alive else self.hp / self.max_hp

    def is_controlled_skip(self):
        return any(c["name"] in SKIP_CONTROLS for c in self.controls)

    def has_control(self):
        return len([c for c in self.controls if c["name"] in CONTROL_KIND]) > 0

    def heal_mult_debuff(self):
        d = sum(1 for c in self.controls if c["name"] == "减疗")
        return 0.5 ** d if d else 1.0


# ----------------------------------------------------------------------------
# 战斗
# ----------------------------------------------------------------------------
class Duel:
    def __init__(self, cfg: dict, seed: int | None = None):
        self.warnings: list[str] = []
        self.rng = random.Random(seed)
        self.max_turns = int(cfg.get("max_unit_turns", 600))
        self.arbiter_period = int(cfg.get("arbiter_period", 5))   # 每 5 个单位回合，裁决鬼王动 1 次
        self.teams: dict[str, list[Unit]] = {}
        for side in ("red", "blue"):
            spec = cfg["teams"][side]
            units = [Unit(u, side, i, self.warnings) for i, u in enumerate(spec["units"])]
            if not units:
                raise ValueError(f"{side} 方没有式神")
            if any("pos" not in u for u in spec["units"]):
                self.warnings.append(
                    f"[阵容序号] {side} 方有式神未提供 pos，已按输入顺序推断 —— "
                    "群攻顺序 4→1→2→3→5 会因此不可靠，请补上界面里的『阵容序号』")
            pos_list = sorted(u.pos for u in units)
            if pos_list != list(range(1, len(units) + 1)):
                self.warnings.append(
                    f"[阵容序号] {side} 方 pos = {pos_list} 不是 1..{len(units)}，"
                    "群攻顺序将退化为按 pos 升序（请核对信息是否拿全）")
            self.teams[side] = units

        self.arbiter_actions = 0
        self.layers = 0
        self.unit_turns = 0
        self.log: list[str] = []
        self._depth = 0            # 反击嵌套深度护栏

        # 开局鬼火与护盾
        self.fire = {s: 4.0 for s in ("red", "blue")}
        self.fire_bar = {s: 0 for s in ("red", "blue")}
        self.fire_refill = {s: 3 for s in ("red", "blue")}
        for side, units in self.teams.items():
            # 火灵（唯一）
            has_火灵 = any("火灵" in u.souls for u in units)
            if has_火灵:
                self.fire[side] += 3
            # 座敷童子先机（可叠加）
            # ⚠️ 必须精确匹配：SP「福悦座敷童子」的先机机制不同，不能用 `in` 匹配
            n_zd = sum(1 for u in units if u.name == "座敷童子")
            if n_zd:
                self.fire[side] += 3 * n_zd
            # ⚠️ SP 与本体同名不同人：出现复合名时提示人工确认
            for u in units:
                if u.name != "座敷童子" and "座敷童子" in u.name:
                    self.warnings.append(
                        f"[SP 去歧义] {u.name} 被识别为 SP 形态，本体是「座敷童子」"
                        "——两者面板/技能不同，模拟按 SP 的输入面板与技能计算，请确认用的是哪个")
            # 蚌精：按携带者生命上限给全队护盾
            for u in units:
                if "蚌精" in u.souls:
                    amt = u.max_hp * 0.10
                    for a in units:
                        a.shield += amt
                    self.warnings.append(f"[蚌精] {u.name} 为 {side} 全队生成护盾 {amt:.0f}")
            # 油赤子：灵元提供全队防御加成
            for u in units:
                if "team_def_bonus" in u.flags:
                    for a in units:
                        a.dfn *= (1.0 + u.flags["team_def_bonus"])
                    self.warnings.append(
                        f"[油赤子] {u.name} 为 {side} 全队 +{u.flags['team_def_bonus']*100:.0f}% 防御")
            self.fire[side] = min(8.0, self.fire[side])

        # 行动条
        self.prog = {u: 0.0 for side in self.teams for u in self.teams[side]}
        self._init_progress()
        self._rng_tiebreak = {u: self.rng.random() * 1e-9 for u in self.prog}

    def _init_progress(self):
        allu = [u for s in self.teams for u in self.teams[s]]
        smax = max(u.base_spd for u in allu)
        for u in allu:
            self.prog[u] = clamp(u.base_spd / smax, 0.0, 1.0)

    # ---------------- 裁决之力 ----------------
    def dmg_bonus(self):
        per = 0.30 if self.arbiter_actions >= 11 else 0.15
        return per * self.layers

    def heal_reduction(self):
        return clamp(0.10 * self.layers, 0.0, 0.95)

    def arbiter_tick(self):
        if self.unit_turns % self.arbiter_period == 0:
            self.arbiter_actions += 1
            self.layers += 1

    # ---------------- 目标选择 ----------------
    def order_key(self, u: Unit):
        return u.pos

    def aoe_targets(self, enemy_side):
        order = [4, 1, 2, 3, 5]
        by_pos = {u.pos: u for u in self.teams[enemy_side] if u.alive}
        out = [by_pos[p] for p in order if p in by_pos]
        for u in self.teams[enemy_side]:
            if u.alive and u not in out:
                out.append(u)
        return out

    def lowest_hp_target(self, enemy_side):
        alive = [u for u in self.teams[enemy_side] if u.alive]
        if not alive:
            return None
        return min(alive, key=lambda u: (u.hp_ratio, u.pos))

    # ---------------- 伤害与命中 ----------------
    def compute_hit(self, base_p, atk_hit, tgt_res):
        p = base_p * (1.0 + atk_hit / 100.0)
        p = clamp(p, 0.0, 1.0)
        p = p / (1.0 + tgt_res / 100.0)
        return clamp(p, 0.0, 1.0)

    def soul_damage_mult(self, atk: Unit, tgt: Unit):
        m = 1.0
        f = atk.flags
        if "dmg_vs_high_hp" in f:
            thr, bonus = f["dmg_vs_high_hp"]
            if tgt.hp_ratio > thr:
                m *= (1.0 + bonus)
        if "dmg_per_missing" in f:
            step, bonus = f["dmg_per_missing"]
            missing = 1.0 - tgt.hp_ratio
            m *= (1.0 + bonus * math.floor(missing / step))
        if "dmg_vs_controlled" in f and tgt.has_control():
            m *= (1.0 + f["dmg_vs_controlled"])
        if "dmg_per_fire" in f:
            m *= (1.0 + f["dmg_per_fire"] * self.fire[atk.side])
        if "dmg_per_death" in f:
            deaths = sum(1 for s in ("red", "blue") for x in self.teams[s] if not x.alive)
            bonus = f["dmg_per_death"] * deaths
            bonus = min(bonus, f.get("dmg_per_death_cap", 9.9))
            m *= (1.0 + bonus)
        # 片叶之苇：满血 +45%
        if "dmg_if_full_hp" in f and atk.hp >= atk.max_hp - 1e-6:
            m *= (1.0 + f["dmg_if_full_hp"])
        # 无刀取：回合结束永久 +15%，上限 45%
        if "ramp_dmg" in f:
            per, cap = f["ramp_dmg"]
            m *= (1.0 + min(per * max(0, atk.turn_count - 1), cap))
        # 恶楼：前 N 回合封禁，之后 +80% 增伤（减伤在 real_damage 里处理）
        if "ramp_after_turns" in f:
            turns, bonus_d, _ = f["ramp_after_turns"]
            if atk.turn_count > turns:
                m *= (1.0 + bonus_d)
        # 海月火玉：额外耗 1 火换 +40%
        if "extra_fire_dmg" in f and atk._cast_bonus:
            m *= (1.0 + atk._cast_bonus)
        # 尘冢：本模拟按 +25% 固定（未实现「友方每多一个 +4%」）
        if "dmg_flat" in f:
            m *= (1.0 + f["dmg_flat"])
        # 八咫镜：实测等效 +12% 平均增伤（2 击一轮 +24%）
        if "dmg_cycle" in f:
            _, bonus = f["dmg_cycle"]
            m *= (1.0 + bonus / 2.0)
        return m

    def flat_def_reduction(self, atk: Unit):
        """御魂带来的「无视 N 点防御」（天羽羽斩 / 兵主部）"""
        f = atk.flags
        r = 0.0
        if "ignore_def_flat" in f:
            r += f["ignore_def_flat"]
        if "ignore_def_stack" in f:
            per, cap = f["ignore_def_stack"]
            r += per * min(cap, atk.turn_count)
        return r

    def team_crit_taken_mult(self, tgt: Unit, crit: bool):
        """叠叩：佩戴者初始暴击 >120% 时，全队减少 15% 受到的暴击伤害"""
        if not crit:
            return 1.0
        for a in self.teams[tgt.side]:
            if not a.alive:
                continue
            if "team_crit_taken_mult" in a.flags:
                thr, mult = a.flags["team_crit_taken_mult"]
                if a.crit > thr:
                    return mult
        return 1.0

    def real_damage(self, atk: Unit, tgt: Unit, coef, hits, allow_crit=True,
                    ignore_def_frac=0.0, tag=""):
        """返回 (到血量的伤害, 被护盾吸收的伤害, 是否暴击过)"""
        total_to_hp = 0.0
        total_to_shield = 0.0
        any_crit = False
        for _ in range(max(1, hits)):
            crit = allow_crit and (self.rng.random() < atk.crit)
            any_crit = any_crit or crit
            cdmg = atk.cdmg
            if "cdmg_per_missing" in atk.flags:
                cdmg += atk.flags["cdmg_per_missing"] * (1.0 - atk.hp_ratio)
            k = cdmg if crit else 1.0
            raw = atk.atk * coef * k
            if crit:
                raw *= self.team_crit_taken_mult(tgt, True)
            eff_def = (tgt.dfn * (1.0 - clamp(ignore_def_frac, 0.0, 1.0))
                       - self.flat_def_reduction(atk))
            raw *= 300.0 / (300.0 + max(-299.0, eff_def))
            red = tgt.passive_reduce
            if "taken_mult" in tgt.flags:
                red = 1.0 - (1.0 - red) * tgt.flags["taken_mult"]
            raw *= tgt._taken_mult_1turn          # 纺缘锤
            if "ramp_after_turns" in tgt.flags:    # 恶楼：8 回合后 -80% 受伤
                turns, _, bonus_r = tgt.flags["ramp_after_turns"]
                if tgt.turn_count > turns:
                    raw *= (1.0 - bonus_r)
            raw *= 1.0 / (1.0 + red)
            raw *= (1.0 + self.dmg_bonus())
            raw *= atk.dmg_mult
            raw *= self.soul_damage_mult(atk, tgt)
            raw *= self.rng.uniform(0.99, 1.01)
            # 护盾优先
            if tgt.shield > 0:
                absorbed = min(tgt.shield, raw)
                tgt.shield -= absorbed
                raw -= absorbed
                total_to_shield += absorbed
            total_to_hp += raw
        return total_to_hp, total_to_shield, any_crit

    def _counter_attack(self, u: Unit, tgt: Unit):
        """被动/御魂触发的普攻反击（单层，防递归）"""
        if self._depth > 0 or not u.alive or not tgt.alive:
            return
        self._depth += 1
        try:
            sk = self.basic_of(u)
            dmg_hp, dmg_sh, crit = self.real_damage(
                u, tgt, float(sk.get("coef", 1.0)), int(sk.get("hits", 1)))
            self.log.append(f"     ↩ {u.name} 反击 {tgt.name}")
            self.apply_damage(u, tgt, dmg_hp, dmg_sh, crit, self.warnings)
        finally:
            self._depth -= 1

    def apply_damage(self, atk: Unit, tgt: Unit, dmg_hp, dmg_shield, crit, warnings):
        """返回 True 表示这次造成了『对血量的伤害』（决定御魂/针女是否触发）"""
        # 出世螺：单次伤害超过最大生命 60% 时降为 60%
        if "dmg_cap_pct" in tgt.flags and dmg_hp + dmg_shield > 0:
            cap = tgt.max_hp * tgt.flags["dmg_cap_pct"]
            total = dmg_hp + dmg_shield
            if total > cap:
                scale = cap / total
                dmg_hp *= scale
                dmg_shield *= scale
        dealt_to_hp = dmg_hp > 0.0
        if dmg_hp > 0:
            tgt.hp -= dmg_hp
        # 出世螺：受击后回复该次伤害的 10%
        if "heal_on_hit" in tgt.flags and (dmg_hp + dmg_shield) > 0 and not tgt.no_heal:
            tgt.hp = min(tgt.max_hp, tgt.hp + (dmg_hp + dmg_shield) * tgt.flags["heal_on_hit"])
        # 纺缘锤：受击后 1 回合内 20% 减伤
        if "taken_mult_after_hit" in tgt.flags and (dmg_hp + dmg_shield) > 0:
            tgt._taken_mult_1turn = tgt.flags["taken_mult_after_hit"]
        # 镜姬反伤
        if "reflect" in tgt.flags:
            p, mult = tgt.flags["reflect"]
            if self.rng.random() < p:
                back = (dmg_hp + dmg_shield) * mult
                self.log.append(f"     ◀ 镜姬反伤 {back:.0f} → {atk.name}")
                self._raw_lose_hp(atk, back, "镜姬反伤")
        # 地藏像：被暴击时生成护盾（自身 100% / 友方各 30%）
        if crit and "crit_shield" in tgt.flags:
            p, pct = tgt.flags["crit_shield"]
            if self.rng.random() < p:
                tgt.shield += tgt.max_hp * pct
            ap = tgt.flags.get("ally_crit_shield_p")
            if ap:
                for a in self.teams[tgt.side]:
                    if a.alive and a is not tgt and self.rng.random() < ap:
                        a.shield += tgt.max_hp * pct
        # 受击眩晕（返魂香）：需造成对血量伤害，且不能被护盾吃掉
        if dealt_to_hp and dmg_shield == 0.0 and "on_being_hit_control" in tgt.flags:
            cname, cp = tgt.flags["on_being_hit_control"]
            self.roll_control(tgt, atk, cname, cp, 1,
                              "hard" if cname in HARD_CONTROLS else "soft", pre_rolled=True)
        # 木魅：友方受伤时概率扣攻击方 1 火
        if dealt_to_hp:
            for a in self.teams[tgt.side]:
                if a.alive and "drain_fire" in a.flags and self.rng.random() < a.flags["drain_fire"]:
                    self.fire[atk.side] = max(0.0, self.fire[atk.side] - 1)
                    self.log.append(f"     ✂ 木魅扣火 1 → {atk.side}")
                    break
        # 狰：受击概率普攻反击
        if dealt_to_hp and tgt.alive and atk.alive and "counter" in tgt.flags:
            if self.rng.random() < tgt.flags["counter"]:
                self._counter_attack(tgt, atk)
        if tgt.hp <= 0:
            self.kill(tgt, atk)
        return dealt_to_hp

    def _raw_lose_hp(self, u: Unit, amount, reason=""):
        if not u.alive or amount <= 0:
            return
        if u.shield > 0:
            a = min(u.shield, amount)
            u.shield -= a
            amount -= a
        u.hp -= amount
        if u.hp <= 0:
            self.kill(u, None)

    # ---------------- 控制 ----------------
    def can_be_controlled(self, u: Unit, name):
        for c in u.controls:
            if c["name"] == name:
                return False
            if name == "睡眠" and c["name"] in ("眩晕", "变形"):
                return False
        return True

    def add_control(self, tgt: Unit, name, turns, kind):
        if not tgt.alive or not self.can_be_controlled(tgt, name):
            return False
        if name in ("眩晕", "变形"):
            tgt.controls = [c for c in tgt.controls if c["name"] != "睡眠"]
        tgt.controls.append({"name": name, "kind": kind, "left": turns,
                             "until_turn": tgt.turn_count + turns})
        return True

    def roll_control(self, attacker: Unit, target: Unit, name, base_p, turns, kind,
                     n_rolls=1, pre_rolled=False):
        """命中两段判定 + 抵抗侧反制（幽谷响反弹 / 骰子鬼反击）"""
        if not target.alive or not attacker.alive:
            return False
        if pre_rolled:
            p = base_p
        else:
            p = self.compute_hit(base_p, attacker.hit, target.res)
            if n_rolls > 1:
                p = 1.0 - (1.0 - p) ** n_rolls
        if self.rng.random() < p:
            return self.add_control(target, name, turns, kind)
        # —— 抵抗成功 → 反制 ——
        if self._depth > 0:
            return False
        if "reflect_control" in target.flags:
            if self.rng.random() < target.flags["reflect_control"]:
                self.log.append(f"     ⇄ 幽谷响反弹「{name}」→ {attacker.name}")
                self.add_control(attacker, name, turns, kind)
        if target.flags.get("counter_on_resist"):
            self._counter_attack(target, attacker)
        return False

    # ---------------- 死亡 ----------------
    def kill(self, u: Unit, killer: Unit | None):
        if not u.alive:
            return
        if u.revive_left > 0:
            u.revive_left -= 1
            u.hp = u.max_hp * 0.35
            u.shield = 0.0
            u.controls.clear()
            self.log.append(f"  ↻ {u.side}/{u.name} 免死触发（剩 {u.revive_left} 次）")
            return
        u.hp = 0.0
        u.alive = False
        u.shield = 0.0
        u.controls.clear()
        if killer is not None:
            killer.kills += 1
            if "fire_on_kill" in killer.flags:
                self.fire[killer.side] = min(8.0, self.fire[killer.side] + killer.flags["fire_on_kill"])
        # 伤魂鸟回血 / 阴摩罗等由持有者自己结算
        for side in ("red", "blue"):
            for a in self.teams[side]:
                if a.alive and "heal_on_death" in a.flags:
                    a.hp = min(a.max_hp, a.hp + a.max_hp * a.flags["heal_on_death"])
        # 夜啼石：友方阵亡时，携带者获得其初始攻击/防御/生命的 30%（上限 5 层）
        for a in self.teams[u.side]:
            if a is u or not a.alive:
                continue
            if "inherit_on_ally_death" in a.flags:
                k = a.flags["inherit_on_ally_death"]
                a._bonus_stacks = min(5, a._bonus_stacks + 1)
                a.atk = min(a.atk + u.base_atk * k, a.base_atk * 1.5 * 1.0 + 0.0)
                a.hp += u.max_hp * k
                a.max_hp += u.max_hp * k
                a.dfn += u.dfn * k
        # 己方非召唤物阵亡 → +1 火
        self.fire[u.side] = min(8.0, self.fire[u.side] + 1)
        self.log.append(f"  ✝ {u.side}/{u.name} 阵亡")

    # ---------------- 回合 ----------------
    def choose_action(self, u: Unit, enemy_side):
        """按技能表的 priority 顺序挑第一个满足条件的技能；否则普攻。"""
        allies = self.teams[u.side]
        alive_allies = [a for a in allies if a.alive]
        alive_enemies = [a for a in self.teams[enemy_side] if a.alive]
        if not alive_enemies:
            return None
        for idx, sk in enumerate(self.skills_of(u)):
            if u.cds.get(idx, 0) > 0:
                continue
            cost = float(sk.get("cost", 0))
            if self.fire[u.side] < cost:
                continue
            cond = sk.get("when", "always")
            ok = True
            if cond == "ally_hp_below":
                ok = any(a.hp_ratio < sk.get("thr", 0.3) for a in alive_allies)
            elif cond == "ally_hp_above":
                ok = all(a.hp_ratio > sk.get("thr", 0.7) for a in alive_allies)
            elif cond == "enemy_has_control":
                ok = any(a.has_control() for a in alive_enemies)
            elif cond == "self_hp_below":
                ok = u.hp_ratio < sk.get("thr", 0.5)
            elif cond == "always":
                ok = True
            if not ok:
                continue
            return idx, sk
        return -1, self.basic_of(u)

    def skills_of(self, u):
        return u.skills

    def basic_of(self, u):
        return u.fallback_basic

    def do_action(self, u: Unit, enemy_side):
        u.turn_count += 1
        for k in list(u.cds):
            u.cds[k] = max(0, u.cds[k] - 1)
        # 控制结算
        skips = u.is_controlled_skip()
        random_target = any(c["name"] == "混乱" for c in u.controls)
        taunt = next((c for c in u.controls if c["name"] in ("嘲讽", "挑衅")), None)
        basic_only = any(c["name"] in ("沉默", "禁锢") for c in u.controls)

        if skips:
            self.log.append(f"  ⛔ {u.side}/{u.name} 被控制（{[c['name'] for c in u.controls]}），跳过行动")
            self.expire_controls(u)
            return

        if basic_only or taunt:
            idx, sk = -1, self.basic_of(u)
        else:
            picked = self.choose_action(u, enemy_side)
            idx, sk = picked if picked is not None else (-1, self.basic_of(u))
        if idx == -1:
            sk = self.basic_of(u)
            u._cast_bonus = 0.0
        else:
            cost = float(sk.get("cost", 0))
            self.fire[u.side] -= cost
            cd = int(sk.get("cd", 0))
            if cd:
                u.cds[idx] = cd
            u._cast_bonus = 0.0
            # 海月火玉：额外耗 1 火换 +40% 伤害
            if "extra_fire_dmg" in u.flags:
                ef, bonus = u.flags["extra_fire_dmg"]
                if self.fire[u.side] >= ef:
                    self.fire[u.side] -= ef
                    u._cast_bonus = bonus
                    self.log.append(f"     ✦ 海月火玉：额外耗 {ef} 火 → +{bonus*100:.0f}% 伤害")

        is_support = bool(sk.get("heal_pct") or sk.get("shield_pct"))

        # 目标
        if is_support:
            targets = [a for a in self.teams[u.side] if a.alive]
        elif taunt is not None:
            tgt = taunt.get("source")
            targets = [tgt] if (tgt is not None and tgt.alive) else []
        elif random_target:
            t = self.rng.choice([e for e in self.teams[enemy_side] if e.alive] or [None])
            targets = [t] if t else []
        elif sk.get("aoe"):
            targets = self.aoe_targets(enemy_side)
        else:
            t = self.lowest_hp_target(enemy_side)
            targets = [t] if t else []

        if not targets:
            self.expire_controls(u)
            return

        if is_support:
            self.log.append(f"  ▶ {u.side}/{u.name} 使用「{sk.get('name','?')}」"
                            f"→ 己方 {[t.name for t in targets[:5]]}")
        else:
            self.log.append(f"  ▶ {u.side}/{u.name} 使用「{sk.get('name','?')}」"
                            f"→ {[t.name for t in targets[:5]]}")

        # 治疗 / 护盾类技能
        if is_support:
            self._resolve_support(u, sk, enemy_side)
        else:
            self._resolve_damage(u, sk, targets, enemy_side)

        self._post_turn_souls(u, used_basic=(idx == -1),
                             dealt_damage=(not is_support and float(sk.get("coef", 0)) > 0))
        self.expire_controls(u)

    def _post_turn_souls(self, u: Unit, used_basic: bool, dealt_damage: bool):
        """回合结束类御魂：共潜（驱散）、涂佛（普攻/被控则给全队 buff）"""
        # 共潜：回合结束随机驱散己方 1 个负面；若回合中未造成伤害则额外 2 个
        if "dispel_on_turn" in u.flags:
            n1, n2 = u.flags["dispel_on_turn"]
            n = n1 if dealt_damage else n2
            allies = sorted([a for a in self.teams[u.side] if a.alive],
                            key=lambda a: -len(a.controls))
            cleared = 0
            for a in allies:
                while n > 0 and a.controls:
                    c = a.controls.pop()          # 从后往前，近似「从下到上」顺序
                    cleared += 1
                    n -= 1
                if n <= 0:
                    break
            if cleared:
                self.log.append(f"     ⊕ 共潜驱散 {cleared} 个负面")
        # 涂佛：本回合普攻或无法动作 → 全队 +15% 抵抗与伤害 2 回合
        if "team_buff_on_basic" in u.flags and (used_basic or u.controls):
            res_b, dmg_b = u.flags["team_buff_on_basic"]
            for a in self.teams[u.side]:
                if a.alive:
                    a.res += res_b * 100
                    a.dmg_mult *= (1.0 + dmg_b)
            self.log.append(f"     ⊕ 涂佛：全队 +{dmg_b*100:.0f}% 伤害 / +{res_b*100:.0f}% 抵抗")

    def _resolve_support(self, u: Unit, sk, enemy_side):
        allies = [a for a in self.teams[u.side] if a.alive]
        if sk.get("shield_pct"):
            amt = u.max_hp * float(sk["shield_pct"])
            for a in allies:
                a.shield += amt
        if sk.get("heal_pct"):
            base = u.max_hp * float(sk["heal_pct"])
            crit = self.rng.random() < u.crit
            if crit:
                base *= u.cdmg
            base *= u.flags.get("heal_mult", 1.0)
            base *= u.heal_mult_debuff()
            base *= max(0.0, 1.0 - self.heal_reduction())
            for a in allies:
                if a.no_heal or not a.alive:
                    continue
                a.hp = min(a.max_hp, a.hp + base)
        self.log.append(f"     ↳ 辅助结算（治疗/护盾）")

    def _resolve_damage(self, u: Unit, sk, targets, enemy_side):
        hits = int(sk.get("hits", 1))
        coef = float(sk.get("coef", 1.0))
        main_coef = float(sk.get("main_coef", coef))
        ctrl = sk.get("control") or {}
        ignore_def_frac = 0.0
        if "ignore_def" in u.flags:
            p, frac = u.flags["ignore_def"]
            if self.rng.random() < p:
                ignore_def_frac = frac
        for i, tgt in enumerate(targets):
            if not tgt.alive:
                continue
            c = main_coef if (i == 0 and sk.get("main_coef")) else coef
            dmg_hp, dmg_sh, crit = self.real_damage(
                u, tgt, c, hits, ignore_def_frac=ignore_def_frac)
            dealt = self.apply_damage(u, tgt, dmg_hp, dmg_sh, crit, self.warnings)

            # 针女：暴击且有对血量伤害
            if dealt and crit and "proc" in u.flags:
                if self.rng.random() < u.flags["proc"]:
                    true_dmg = min(tgt.max_hp * u.flags["hp_pct"],
                                   u.atk * u.flags["cap_atk_mult"])
                    self._raw_lose_hp(tgt, true_dmg, "针女")
                    self.log.append(f"     ✦ 针女真伤 {true_dmg:.0f} → {tgt.name}")

            # 御魂控制（必须造成对血量伤害）
            if dealt:
                self._soul_control(u, tgt, sk)

            # 技能自带控制
            if ctrl and ctrl.get("type") and tgt.alive:
                n_rolls = 1 if ctrl.get("single_roll") else max(1, hits)
                self.roll_control(u, tgt, ctrl["type"],
                                  float(ctrl.get("p", 0)),
                                  int(ctrl.get("turns", 1)),
                                  "hard" if ctrl["type"] in HARD_CONTROLS else "soft",
                                  n_rolls=n_rolls)

    def _soul_control(self, u: Unit, tgt: Unit, sk):
        f = u.flags
        n_rolls = max(1, int(sk.get("hits", 1)))
        if "on_hit_control" in f:
            name, base_p, kind = f["on_hit_control"]
            bp = base_p
            if name == "冰冻" and "control_boost_if_slowed" in f:
                if any(c["name"] == "减速" for c in tgt.controls):
                    bp = f["control_boost_if_slowed"]
            self.roll_control(u, tgt, name, bp, 1, kind, n_rolls=n_rolls)
        if "random_control" in f:
            base_p = float(f["random_control_p"])
            if self.rng.random() < 1.0 - (1.0 - self.compute_hit(base_p, u.hit, tgt.res)) ** n_rolls:
                name = self.rng.choice(f["random_control"])
                if name == "减疗":
                    self.add_control(tgt, "减疗", 2, "soft")
                else:
                    self.add_control(tgt, name, 1,
                                     "hard" if name in HARD_CONTROLS else "soft")
        if "push_on_hit" in f:
            p, amt = f["push_on_hit"]
            if tgt.has_control():
                p += f.get("push_bonus_if_buffed", 0.0)
            if self.rng.random() < p:
                self.prog[tgt] = max(0.0, self.prog[tgt] - amt)
                self.log.append(f"     ⇩ 日女巳时推条 {amt*100:.0f}% → {tgt.name}")

    def expire_controls(self, u: Unit):
        rest = []
        for c in u.controls:
            if u.turn_count >= c["until_turn"]:
                continue
            rest.append(c)
        u.controls = rest

    # ---------------- 主循环 ----------------
    def run(self):
        while self.unit_turns < self.max_turns:
            live_sides = [s for s in ("red", "blue") if any(x.alive for x in self.teams[s])]
            if len(live_sides) < 2:
                return self.finish(reason="wipe")
            # 推进到最近一个到达终点者
            actives = [u for s in ("red", "blue") for u in self.teams[s] if u.alive]
            if not actives:
                break
            dt = min((1.0 - self.prog[u]) / max(1e-6, u.base_spd) for u in actives)
            for u in actives:
                self.prog[u] += u.base_spd * dt
            ready = [u for u in actives if self.prog[u] >= 1.0 - 1e-12]
            ready.sort(key=lambda u: (-u.base_spd, self._rng_tiebreak[u]))
            for u in ready:
                if not u.alive:
                    continue
                self.prog[u] -= 1.0
                self.unit_turns += 1
                if self.unit_turns % self.arbiter_period == 0:
                    self.arbiter_tick()
                enemy = "blue" if u.side == "red" else "red"
                if not any(x.alive for x in self.teams[enemy]):
                    return self.finish(reason="wipe")
                self.do_action(u, enemy)
                # 回合结束：涅槃之火 / 招财猫 / 鬼火条
                if u.alive and "heal_low_hp" in u.flags:
                    thr, amt = u.flags["heal_low_hp"]
                    if u.hp_ratio < thr and not u.no_heal:
                        u.hp = min(u.max_hp, u.hp + u.max_hp * amt)
                if u.alive and "fire_on_turn" in u.flags:
                    p, amt = u.flags["fire_on_turn"]
                    if self.rng.random() < p:
                        self.fire[u.side] = min(8.0, self.fire[u.side] + amt)
                # 钓瓶火：额外推进 1 格鬼火条 + 治疗当前生命比例最低的友方（防御 700%）
                step = 1
                if u.alive and "fire_bar_extra" in u.flags:
                    step += u.flags["fire_bar_extra"]
                self.fire_bar[u.side] += step
                if self.fire_bar[u.side] >= 5:
                    self.fire_bar[u.side] = 0
                    self.fire[u.side] = min(8.0, self.fire[u.side] + self.fire_refill[u.side])
                    self.fire_refill[u.side] = min(5, self.fire_refill[u.side] + 1)
                if u.alive and "heal_lowest_def_pct" in u.flags:
                    allies = [a for a in self.teams[u.side] if a.alive and not a.no_heal]
                    if allies:
                        t = min(allies, key=lambda a: a.hp_ratio)
                        amt = u.dfn * u.flags["heal_lowest_def_pct"]
                        t.hp = min(t.max_hp, t.hp + amt)
                if u.alive and "extra_turn" in u.flags:
                    if self.rng.random() < u.flags["extra_turn"]:
                        self.prog[u] = 1.0
                # 火之车：每 4 回合获得 1 个额外回合（该回合鬼火消耗 −1，本模拟未实现减费）
                if u.alive and "extra_turn_ramp" in u.flags:
                    if u.turn_count % u.flags["extra_turn_ramp"] == 0:
                        self.prog[u] = 1.0
                        self.log.append(f"     ↻ 火之车：{u.name} 获得额外回合")
                # 回合结束清掉受击类临时减伤
                u._taken_mult_1turn = 1.0
                if not any(x.alive for x in self.teams[enemy]):
                    return self.finish(reason="wipe")
        return self.finish(reason="timeout")

    def finish(self, reason):
        red_alive = [u for u in self.teams["red"] if u.alive]
        blue_alive = [u for u in self.teams["blue"] if u.alive]
        if red_alive and not blue_alive:
            winner = "red"
        elif blue_alive and not red_alive:
            winner = "blue"
        elif not red_alive and not blue_alive:
            winner = "draw"
        else:
            # 平局兜底
            if len(red_alive) != len(blue_alive):
                winner = "red" if len(red_alive) > len(blue_alive) else "blue"
            else:
                rh = sum(u.hp for u in red_alive)
                bh = sum(u.hp for u in blue_alive)
                if abs(rh - bh) < 1e-6:
                    winner = "draw"
                else:
                    winner = "red" if rh > bh else "blue"
        return {
            "winner": winner,
            "reason": reason,
            "unit_turns": self.unit_turns,
            "arbiter_actions": self.arbiter_actions,
            "layers": self.layers,
            "red_alive": len(red_alive),
            "blue_alive": len(blue_alive),
            "red_hp": sum(u.hp for u in red_alive),
            "blue_hp": sum(u.hp for u in blue_alive),
        }


# ----------------------------------------------------------------------------
# 驱动
# ----------------------------------------------------------------------------
def preflight(cfg):
    warn = []
    for side in ("red", "blue"):
        for u in cfg["teams"][side]["units"]:
            if u.get("role") in ("dps", "output") and float(u.get("crit", 100)) < 100:
                warn.append(
                    f"[未满暴] {u.get('name')} 暴击 {u.get('crit')}% < 100% —— "
                    f"暴伤属性近乎归零，请按知识库 02 §2.8 打折")
    return warn


def simulate(cfg, trials, seed):
    res = {"red": 0, "blue": 0, "draw": 0}
    turns, layers, alive_r, alive_b = [], [], [], []
    for i in range(trials):
        d = Duel(cfg, seed=(None if seed is None else seed + i))
        r = d.run()
        res[r["winner"]] += 1
        turns.append(r["unit_turns"])
        layers.append(r["layers"])
        alive_r.append(r["red_alive"])
        alive_b.append(r["blue_alive"])
        last = d
    n = trials
    return {
        "win_rate": {k: v / n for k, v in res.items()},
        "counts": res,
        "avg_unit_turns": statistics.fmean(turns),
        "avg_arbiter_actions": statistics.fmean(layers),
        "avg_alive": {"red": statistics.fmean(alive_r), "blue": statistics.fmean(alive_b)},
        "warnings": sorted(set(last.warnings)),
    }


def perturb(cfg, path, factor):
    """返回一份被修改的 cfg（深拷贝，走 json round-trip）"""
    c = json.loads(json.dumps(cfg))
    for u in c["teams"][path[0]]["units"]:
        if path[1] == "*" or u.get("name") == path[1]:
            if path[2] == "spd":
                u["spd"] = float(u.get("spd", 100)) * (1 + factor)
            elif path[2] == "crit":
                u["crit"] = max(0.0, float(u.get("crit", 100)) + factor * 100)
            elif path[2] == "ctrl_p":
                for sk in u.get("skills", []):
                    if sk.get("control"):
                        sk["control"]["p"] = clamp(
                            float(sk["control"].get("p", 0)) * (1 + factor), 0.0, 1.0)
    return c


def sensitivity(cfg, trials, seed, base):
    out = []
    scenarios = [
        ("红方全体速度 +5%", ("red", "*", "spd"), 0.05),
        ("蓝方全体速度 +5%", ("blue", "*", "spd"), 0.05),
        ("红方全体速度 -5%", ("red", "*", "spd"), -0.05),
        ("蓝方全体速度 -5%", ("blue", "*", "spd"), -0.05),
        ("双方控制基础概率 +20%（相对）", ("red", "*", "ctrl_p"), 0.20),
        ("双方控制基础概率 -20%（相对）", ("red", "*", "ctrl_p"), -0.20),
        ("双方输出暴击 -10pt", ("red", "*", "crit"), -0.10),
    ]
    for label, path, factor in scenarios:
        c = perturb(cfg, path, factor)
        if path[1] == "*" and path[0] == "red" and path[2] == "ctrl_p":
            for u in c["teams"]["blue"]["units"]:
                for sk in u.get("skills", []):
                    if sk.get("control"):
                        sk["control"]["p"] = clamp(
                            float(sk["control"].get("p", 0)) * (1 + factor), 0.0, 1.0)
        if path[1] == "*" and path[2] == "crit":
            for side in ("red", "blue"):
                for u in c["teams"][side]["units"]:
                    u["crit"] = max(0.0, float(u.get("crit", 100)) - 10)
        r = simulate(c, max(2000, trials // 4), seed)
        out.append({
            "scenario": label,
            "red_win": r["win_rate"]["red"],
            "delta_red": r["win_rate"]["red"] - base["win_rate"]["red"],
        })
    return out


def main():
    ap = argparse.ArgumentParser(description="对弈竞猜蒙特卡洛模拟器")
    ap.add_argument("lineup", help="阵容 JSON 文件路径")
    ap.add_argument("--trials", type=int, default=20000)
    ap.add_argument("--seed", type=int, default=20260924)
    ap.add_argument("--out", default="sim_result.json")
    ap.add_argument("--sensitivity", action="store_true", help="额外跑敏感性分析")
    ap.add_argument("--log", action="store_true", help="打印单局战斗日志（调试用）")
    a = ap.parse_args()

    with open(a.lineup, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    base = simulate(cfg, a.trials, a.seed)
    result = {
        # 只记文件名，不记绝对路径（避免把使用者本机目录带进结果文件）
        "lineup_file": os.path.basename(a.lineup),
        "trials": a.trials,
        "seed": a.seed,
        "preflight": preflight(cfg),
        "result": base,
        "assumptions": ASSUMPTIONS,
        "warnings": base["warnings"],
    }
    if a.sensitivity:
        result["sensitivity"] = sensitivity(cfg, a.trials, a.seed, base)

    if a.log:
        d = Duel(cfg, seed=a.seed)
        d.run()
        result["sample_battle_log"] = d.log[:400]

    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    w = base["win_rate"]
    print(f"红方 {w['red']*100:.1f}% | 蓝方 {w['blue']*100:.1f}% | 平局 {w['draw']*100:.1f}%")
    print(f"平均单位回合 {base['avg_unit_turns']:.0f}，裁决层数 {base['avg_arbiter_actions']:.1f}")
    for x in result["preflight"] + result["warnings"]:
        print("⚠ " + x)
    print(f"结果已写入 {a.out}")


if __name__ == "__main__":
    main()
