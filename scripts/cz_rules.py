"""Explainable bilingual heuristics; these labels are not trading predictions."""
import re
import unicodedata

RULE_VERSION = "cz-rules-v1"
PATTERNS = {
    "asset": r"\b(?:btc|bitcoin)\b|比特币|比特幣",
    "buy": r"\b(?:buy|buying|bought|accumulat(?:e|ing|ion)|stack(?:ing)? sats)\b|买入|買入|抄底|建仓|建倉|囤币|囤幣",
    "opportunity": r"\b(?:opportunit(?:y|ies)|bargain|best time)\b|机会|機會|最佳|便宜筹码",
    "downturn": r"\b(?:dip|dips|crash|crashes|dead|fear|downturn|bear market)\b|下跌|暴跌|完蛋|归零|歸零|恐慌|熊市",
    "long_term": r"\b(?:long[ -]term|patience|patient|future self|thank yourself|(?:two|five|ten|2|5|10) years? from now)\b|长期|長期|耐心|(?:两|兩|2)年后.{0,16}(?:感谢|感謝)|未来的自己|未來的自己|感谢今天|感謝今天",
    "negative": r"\b(?:do not|don't|don’t|never|avoid|stop|not to)\s+(?:\w+\s+){0,2}(?:buy|buying|accumulate)\b|\bnot\s+(?:a\s+)?(?:buy|buying|opportunity)\b|不要买|不要買|不应买|不應買|不适合买|不適合買|不是.{0,4}(?:机会|機會)",
    "promotion": r"\b(?:giveaway|airdrop|referral|promo code|register now)\b|抽奖|抽獎|邀请码|邀請碼|注册送|註冊送",
}
LABELS = {"asset": "资产", "buy": "买入表达", "opportunity": "机会表达",
          "downturn": "逆向语境", "long_term": "长期叙述", "negative": "否定买入", "promotion": "推广内容"}


def analyze_post(post):
    text = unicodedata.normalize("NFKC", post["text"])
    hits = {key: list(dict.fromkeys(m.group(0) for m in re.finditer(pattern, text, re.I)))[:8]
            for key, pattern in PATTERNS.items()}
    reasons = [f"{LABELS[k]}：{'、'.join(v)}" for k, v in hits.items() if v]
    # Count pictographs approximately; explicitly a heuristic, not emoji grapheme count.
    emoji_count = len(re.findall(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", text))
    text_style = post.get("has_media") is False and emoji_count <= 2
    if text_style:
        reasons.append("文风辅助：无已知媒体、少量或无 emoji")
    level, summary = "none", "未命中机会表达规则"
    if hits["negative"]:
        level, summary = "excluded", "包含否定买入表达，暂不作为机会提示"
    elif hits["promotion"] or post.get("kind") in ("retweet", "reply"):
        level, summary = "excluded", "推广、转推或回复，仅保留原文供核对"
    elif hits["buy"] and (hits["asset"] or hits["downturn"] or hits["opportunity"]):
        level, summary = "explicit", "出现买入倾向及资产或机会语境"
    elif hits["opportunity"] and (hits["downturn"] or hits["asset"]):
        level, summary = "opportunity", "出现逆向或资产机会表达，未必明确建议买入"
    elif hits["long_term"] and (text_style or hits["asset"] or hits["buy"] or hits["opportunity"]):
        level, summary = "implicit", "疑似长期叙述；是否暗示买入仍需阅读原文"
    if level in ("explicit", "opportunity", "implicit"):
        if post.get("kind") in ("quote", "unknown") or post.get("text_complete") is not True:
            level, summary = "review", "存在相关表达，但引用关系或正文完整性待确认"
    return {"version": RULE_VERSION, "level": level, "summary": summary,
            "reasons": reasons, "keywords": [x for values in hits.values() for x in values],
            "text_style": text_style, "emoji_count_approx": emoji_count}
