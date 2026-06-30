#!/usr/bin/env python3
"""
希望AI - 自动化左右互搏训练脚本
功能：
  1. 自动调用 Cloudflare Workers AI API，两个AI轮流辩论
  2. 自动生成经验总结并存入经验库
  3. 支持 RAG 检索，把历史经验注入到新的对话中

使用方法：
  python debate_trainer.py --topic "AI会取代程序员吗" --rounds 10
"""

import json
import os
import time
import argparse
import sys
from pathlib import Path
from urllib import request, error

# ============ 配置 ============

# Cloudflare 配置（从环境变量读取）
CF_ACCOUNT_ID = os.environ.get("CF_ACCOUNT_ID", "")
CF_API_TOKEN = os.environ.get("CF_API_TOKEN", "")
CF_MODEL = os.environ.get("CF_MODEL", "@cf/deepseek-ai/deepseek-r1-distill-qwen-32b")

# 经验库文件路径
EXPERIENCE_FILE = Path(__file__).parent / "data" / "experience_library.json"

# 红蓝方人设
RED_PERSONA = {
    "name": "红方（攻击方）",
    "style": "aggressive",
    "prompt": """你是一位犀利的红方辩手，以攻击著称。
你的特点：
- 逻辑严密，善于抓对方漏洞
- 语言犀利，一针见血
- 擅长用反问和归谬法
- 喜欢举反例
- 语速快，进攻性强
辩论时要主动出击，找出对方观点的弱点狠狠打击！"""
}

BLUE_PERSONA = {
    "name": "蓝方（防守方）",
    "style": "defensive",
    "prompt": """你是一位沉稳的蓝方辩手，以防守和反击著称。
你的特点：
- 思维缜密，防守滴水不漏
- 善于化解对方攻击
- 擅长用数据和事实说话
- 反击时精准有力
- 语气沉稳，不慌不忙
辩论时先守住自己的观点，然后找机会反击！"""
}


# ============ 工具函数 ============

def call_ai_api(messages, temperature=0.8, max_tokens=1024):
    """调用 Cloudflare Workers AI API"""
    if not CF_ACCOUNT_ID or not CF_API_TOKEN:
        raise ValueError("请设置 CF_ACCOUNT_ID 和 CF_API_TOKEN 环境变量")

    url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/ai/run/{CF_MODEL}"

    payload = {
        "messages": messages,
        "stream": False,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    req = request.Request(url, data=json.dumps(payload).encode("utf-8"))
    req.add_header("Authorization", f"Bearer {CF_API_TOKEN}")
    req.add_header("Content-Type", "application/json")

    try:
        with request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if not data.get("success"):
                raise Exception(f"API 调用失败: {data.get('errors', '未知错误')}")
            return data["result"]["choices"][0]["message"]["content"]
    except error.HTTPError as e:
        raise Exception(f"HTTP 错误 {e.code}: {e.read().decode('utf-8')}")
    except Exception as e:
        raise Exception(f"API 调用异常: {e}")


def load_experience_library():
    """加载经验库"""
    if not EXPERIENCE_FILE.exists():
        return {"experiences": [], "stats": {"total": 0, "categories": {}}}
    with open(EXPERIENCE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_experience_library(library):
    """保存经验库"""
    EXPERIENCE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(EXPERIENCE_FILE, "w", encoding="utf-8") as f:
        json.dump(library, f, ensure_ascii=False, indent=2)


def search_experiences(query, top_k=3):
    """从经验库中检索相关经验（简单关键词匹配）"""
    library = load_experience_library()
    experiences = library.get("experiences", [])

    if not experiences:
        return []

    # 简单关键词匹配
    query_keywords = set(query.lower().split())
    scored = []

    for exp in experiences:
        score = 0
        # 匹配标题
        title_words = set(exp.get("title", "").lower().split())
        score += len(query_keywords & title_words) * 3
        # 匹配标签
        tags = set(exp.get("tags", []))
        score += len(query_keywords & tags) * 5
        # 匹配内容摘要
        summary_words = set(exp.get("summary", "").lower().split())
        score += len(query_keywords & summary_words) * 2
        # 匹配漏洞/方案描述
        weakness_words = set(exp.get("weakness", "").lower().split())
        score += len(query_keywords & weakness_words) * 4
        fix_words = set(exp.get("fix_solution", "").lower().split())
        score += len(query_keywords & fix_words) * 4

        if score > 0:
            scored.append((score, exp))

    # 按分数排序，取 top_k
    scored.sort(key=lambda x: x[0], reverse=True)
    return [exp for _, exp in scored[:top_k]]


def build_experience_prompt(query):
    """构建经验注入的 prompt 片段"""
    experiences = search_experiences(query)
    if not experiences:
        return ""

    prompt = "\n\n=== 📚 历史经验参考 ===\n"
    prompt += "（以下是之前左右互搏积累的经验，供你参考）\n\n"
    for i, exp in enumerate(experiences, 1):
        prompt += f"【经验 {i}】{exp.get('title', '无标题')}\n"
        prompt += f"  漏洞点：{exp.get('weakness', '未知')}\n"
        prompt += f"  应对方案：{exp.get('fix_solution', '未知')}\n"
        prompt += f"  难度：{exp.get('difficulty', '中等')}\n\n"
    prompt += "=== 经验参考结束 ===\n\n"
    return prompt


# ============ 辩论逻辑 ============

def run_debate_round(topic, round_num, history, inject_experience=True):
    """执行一轮辩论（红蓝各一次发言）"""

    print(f"\n{'='*60}")
    print(f"⚔️ 第 {round_num} 轮辩论")
    print(f"{'='*60}")

    # 经验注入（只在第一轮注入，避免 prompt 太长）
    experience_prompt = build_experience_prompt(topic) if inject_experience and round_num == 1 else ""

    # ---- 红方发言 ----
    print(f"\n🔴 {RED_PERSONA['name']} 思考中...")

    red_messages = [
        {"role": "system", "content": RED_PERSONA["prompt"] + experience_prompt},
        {"role": "user", "content": f"""辩题：{topic}

你是红方，你的立场是：支持这个观点。
请进行第 {round_num} 轮发言。

要求：
1. 先回应对方上一轮的观点（如果有的话）
2. 然后提出新的攻击点
3. 要有理有据，逻辑清晰
4. 字数 200-400 字
5. 直接输出辩词，不要加前缀

之前的辩论历史：
{format_history(history)}

现在开始你的第 {round_num} 轮发言："""}
    ]

    red_speech = call_ai_api(red_messages, temperature=0.9)
    print(f"🔴 红方发言：\n{red_speech}\n")
    history.append({"role": "red", "content": red_speech})

    # ---- 蓝方发言 ----
    print(f"🔵 {BLUE_PERSONA['name']} 思考中...")

    blue_messages = [
        {"role": "system", "content": BLUE_PERSONA["prompt"] + experience_prompt},
        {"role": "user", "content": f"""辩题：{topic}

你是蓝方，你的立场是：反对这个观点。
请进行第 {round_num} 轮发言。

要求：
1. 先回应对方刚才的发言
2. 然后阐述你方的观点
3. 要有理有据，逻辑清晰
4. 字数 200-400 字
5. 直接输出辩词，不要加前缀

之前的辩论历史：
{format_history(history)}

现在开始你的第 {round_num} 轮发言："""}
    ]

    blue_speech = call_ai_api(blue_messages, temperature=0.9)
    print(f"🔵 蓝方发言：\n{blue_speech}\n")
    history.append({"role": "blue", "content": blue_speech})

    return history


def format_history(history):
    """格式化历史对话"""
    if not history:
        return "（这是第一轮，还没有历史）"

    result = ""
    for i, msg in enumerate(history, 1):
        side = "🔴 红方" if msg["role"] == "red" else "🔵 蓝方"
        result += f"{side}：{msg['content']}\n\n"
    return result


def generate_experience(topic, history):
    """让 AI 自动总结经验，生成 JSON 格式的经验条目"""
    print("\n📝 正在生成经验总结...")

    history_text = format_history(history)

    prompt = f"""你是一位辩论经验分析师。请分析以下辩论赛，提取出有价值的经验教训。

辩题：{topic}

辩论过程：
{history_text}

请输出一个 JSON 对象，包含以下字段：
{{
  "title": "经验标题（简短有力，10字以内）",
  "category": "分类（如：逻辑漏洞、论据不足、技巧失误、表达问题等）",
  "weakness": "发现的漏洞/问题点（一句话）",
  "fix_solution": "应对方案/改进方法（一句话）",
  "difficulty": "难度（简单/中等/困难）",
  "summary": "经验要点总结（50字以内）",
  "tags": ["标签1", "标签2", "标签3"],
  "side": "哪一方的问题（red/blue/both）"
}}

只输出 JSON，不要输出其他内容。"""

    try:
        result = call_ai_api(
            [{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=512
        )
        # 尝试提取 JSON
        result = result.strip()
        if result.startswith("```json"):
            result = result[7:]
        if result.endswith("```"):
            result = result[:-3]
        result = result.strip()

        # 找第一个 { 和最后一个 }
        start = result.find("{")
        end = result.rfind("}")
        if start >= 0 and end > start:
            result = result[start:end+1]

        exp = json.loads(result)
        exp["topic"] = topic
        exp["timestamp"] = int(time.time())
        exp["id"] = f"exp_{int(time.time())}_{len(load_experience_library()['experiences'])}"

        print(f"✅ 经验生成成功：{exp.get('title', '无标题')}")
        return exp
    except Exception as e:
        print(f"❌ 经验生成失败：{e}")
        return None


def judge_debate(topic, history):
    """AI 裁判打分"""
    print("\n🏆 裁判正在评判...")

    history_text = format_history(history)

    prompt = f"""你是一位公正的辩论赛裁判。请评判以下辩论赛。

辩题：{topic}

辩论过程：
{history_text}

请给出你的评判结果（用 JSON 格式）：
{{
  "winner": "red 或 blue 或 tie",
  "red_score": 85,
  "blue_score": 82,
  "red_advantages": ["优点1", "优点2"],
  "red_weaknesses": ["缺点1", "缺点2"],
  "blue_advantages": ["优点1", "优点2"],
  "blue_weaknesses": ["缺点1", "缺点2"],
  "summary": "一句话总结"
}}

只输出 JSON，不要输出其他内容。"""

    try:
        result = call_ai_api(
            [{"role": "user", "content": prompt}],
            temperature=0.5,
            max_tokens=512
        )
        result = result.strip()
        if result.startswith("```json"):
            result = result[7:]
        if result.endswith("```"):
            result = result[:-3]
        result = result.strip()

        start = result.find("{")
        end = result.rfind("}")
        if start >= 0 and end > start:
            result = result[start:end+1]

        judge = json.loads(result)
        print(f"📊 红方得分：{judge.get('red_score', '?')}")
        print(f"📊 蓝方得分：{judge.get('blue_score', '?')}")
        winner = judge.get("winner", "tie")
        if winner == "red":
            print(f"🏆 胜者：红方")
        elif winner == "blue":
            print(f"🏆 胜者：蓝方")
        else:
            print(f"🤝 平局")
        return judge
    except Exception as e:
        print(f"❌ 裁判失败：{e}")
        return None


# ============ 主流程 ============

def main():
    parser = argparse.ArgumentParser(description="希望AI - 自动化左右互搏训练")
    parser.add_argument("--topic", type=str, required=True, help="辩题")
    parser.add_argument("--rounds", type=int, default=5, help="辩论轮数（默认5）")
    parser.add_argument("--no-experience", action="store_true", help="禁用经验注入")
    parser.add_argument("--save", action="store_true", help="保存经验到经验库")

    args = parser.parse_args()

    print(f"\n{'='*60}")
    print("⚔️  希望AI - 自动化左右互搏训练")
    print(f"{'='*60}")
    print(f"📝 辩题：{args.topic}")
    print(f"🔄 轮数：{args.rounds}")
    print(f"📚 经验注入：{'开启' if not args.no_experience else '关闭'}")
    print(f"💾 保存经验：{'开启' if args.save else '关闭'}")

    library = load_experience_library()
    print(f"📚 当前经验库：{library['stats']['total']} 条经验")

    history = []
    start_time = time.time()

    try:
        for i in range(1, args.rounds + 1):
            history = run_debate_round(
                args.topic,
                i,
                history,
                inject_experience=not args.no_experience
            )

            # 每两轮生成一次经验
            if args.save and i % 2 == 0:
                exp = generate_experience(args.topic, history)
                if exp:
                    library["experiences"].append(exp)
                    library["stats"]["total"] += 1
                    cat = exp.get("category", "其他")
                    library["stats"]["categories"][cat] = library["stats"]["categories"].get(cat, 0) + 1
                    save_experience_library(library)

            # 防止 API 限流
            time.sleep(2)

    except KeyboardInterrupt:
        print("\n⏹️  用户中断")
    except Exception as e:
        print(f"\n❌ 出错了：{e}")

    # 最终裁判
    if history:
        judge = judge_debate(args.topic, history)
    else:
        judge = None

    elapsed = time.time() - start_time
    print(f"\n{'='*60}")
    print(f"✅ 训练完成！用时：{elapsed:.1f} 秒")
    if args.save:
        print(f"📚 经验库现在有：{library['stats']['total']} 条经验")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
