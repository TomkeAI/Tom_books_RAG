"""应用配置管理 — 自动发现 + skill-EPUB 映射"""
import os
import glob
import re
import logging
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


class Settings:
    # LLM（运行时可通过 API 切换）
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_base_url: str = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
    llm_model: str = os.getenv("LLM_MODEL", "deepseek-v4-flash")
    longcat_api_key: str = os.getenv("LONGCAT_API_KEY", "")
    longcat_base_url: str = "https://api.longcat.chat/openai/v1"
    longcat_model: str = "LongCat-2.0"
    _current_provider: str = "deepseek"  # "deepseek" | "longcat"

    @property
    def has_llm(self) -> bool:
        return bool(self.llm_api_key) and self.llm_api_key not in ("", "sk-your-api-key")

    def switch_model(self, provider: str) -> dict:
        """切换到指定模型 provider"""
        if provider == "deepseek":
            self._current_provider = "deepseek"
            # 从环境变量读，兼容 .env 配置
            import os as _os
            self.llm_api_key = _os.getenv("LLM_API_KEY", self.llm_api_key)
            self.llm_base_url = _os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
            self.llm_model = _os.getenv("LLM_MODEL", "deepseek-v4-flash")
            return {"provider": "deepseek", "model": self.llm_model}
        elif provider == "longcat":
            self._current_provider = "longcat"
            self.llm_api_key = self.longcat_api_key
            self.llm_base_url = self.longcat_base_url
            self.llm_model = self.longcat_model
            return {"provider": "longcat", "model": self.longcat_model}
        return {"error": f"未知 provider: {provider}"}

    # Chroma
    chroma_persist_dir: str = os.getenv("CHROMA_PERSIST_DIR", "./data/chroma")
    collection_name: str = os.getenv("COLLECTION_NAME", "books_rag")

    # Server
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "8000"))
    top_k: int = 5
    chunk_size: int = 1024
    web_search: bool = os.getenv("WEB_SEARCH", "true").lower() == "true"
    bocha_api_key: str = os.getenv("BOCHA_API_KEY", "")

    # 目录
    books_base: str = os.path.expanduser("~/.codebuddy/skills")
    epub_dir: str = os.getenv("EPUB_DIR", "./books")

    # ===== skill 目录名 → 中文显示名 =====
    _skill_titles = {
        "alison-rapport": "Rapport: 读懂他人的四步法",
        "die-with-zero": "Die with Zero: 人生最大化",
        "on-confidence": "On Confidence: 自信的力量",
        "on-desire": "On Desire: 欲望心理学",
        "status-anxiety": "Status Anxiety: 身份焦虑",
        "the-blueprint-decoded": "The Blueprint Decoded: 社交蓝图",
        "the-stoic-challenge": "The Stoic Challenge: 斯多葛挑战",
        "what-i-learned-from-darwin": "What I Learned from Darwin: 达尔文投资学",
        "duanyongping-investing": "段永平投资问答录",
        "munger-poor-charlie": "Poor Charlie's Almanack: 芒格智慧",
        "relationships-school-of-life": "Relationships: 亲密关系",
        "on-love-alain-de-botton": "On Love: 爱情哲学",
        "guide-to-good-life": "A Guide to the Good Life: 美好生活指南",
        "slap-in-the-face": "A Slap in the Face: 为何侮辱伤人",
        "thinking-fast-slow": "Thinking, Fast and Slow: 思考快与慢",
        "atomic-habits": "Atomic Habits: 原子习惯",
        "influence": "Influence: 影响力",
        "the-innovators-dilemma": "The Innovator's Dilemma: 创新者的窘境",
        "the-selfish-gene": "The Selfish Gene: 自私的基因",
        "finding-flow": "Flow: 心流",
        "the-happiness-hypothesis": "The Happiness Hypothesis: 象与骑象人",
        "mans-search-for-meaning": "活出生命的意义",
        "meditations": "Meditations: 沉思录",
        "on-the-shortness-of-life": "论生命之短暂",
        "the-enchiridion": "The Enchiridion: 爱比克泰德手册",
        "the-psychology-of-money": "The Psychology of Money: 金钱心理学",
        "same-as-ever": "Same as Ever: 一如既往",
        "superforecasting": "Superforecasting: 超预测",
        "nudge": "Nudge: 助推",
        "why-we-sleep": "Why We Sleep: 我们为什么睡觉",
        "spoon-fed": "Spoon-Fed: 被喂食",
        "anti-inflammation-life": "抗炎生活",
        "abundance": "Abundance: 富足未来",
        "how-to-create-chemistry": "How to Create Chemistry with Anyone: 社交化学",
        "i-hear-you": "I Hear You: 倾听的力量",
        "more-than-you-know": "More Than You Know: 投资真知",
        "sell-with-a-story": "Sell with a Story: 用故事销售",
        "daodejing-survival": "《道德经》无反馈期生存指南",
        "money-mindset-prison": "穷人富人和中产的思维程序牢笼",
        "how-to-get-lucky": "How to Get Lucky: 如何变幸运",
        "nick-zak-capitalism": "Nick and Zak's Adventures in Capitalism",
        "think-twice": "Think Twice: 三思而后行",
    }

    _skill_epub_map = {
        "alison-rapport": ["rapport", "alison"],
        "die-with-zero": ["die with zero"],
        "on-confidence": ["on confidence"],
        "on-desire": ["on desire"],
        "status-anxiety": ["status anxiety"],
        "the-blueprint-decoded": ["blueprint", "the blueprint"],
        "the-stoic-challenge": ["stoic challenge"],
        "what-i-learned-from-darwin": ["what i learned", "darwin"],
        "finding-flow": ["finding flow", "flow psychology", "engagement with everyday"],
        "the-happiness-hypothesis": ["happiness hypothesis", "haidt"],
        "mans-search-for-meaning": ["活出生命的意义", "man's search for meaning", "frankl"],
        "meditations": ["meditations", "marcus aurelius"],
        "on-the-shortness-of-life": ["论生命之短暂", "shortness of life", "seneca"],
        "the-enchiridion": ["enchiridion", "epictetus"],
        "the-psychology-of-money": ["psychology of money", "morgan housel"],
        "same-as-ever": ["same as ever", "morgan housel"],
        "superforecasting": ["superforecasting", "tetlock"],
        "nudge": ["nudge", "thaler", "sunstein"],
        "why-we-sleep": ["why we sleep", "matthew walker"],
        "spoon-fed": ["spoon-fed", "spoon fed", "tim spector"],
        "anti-inflammation-life": ["抗炎", "anti-inflammation"],
        "competition-demystified": ["competition demystified"],
        "duanyongping-investing": ["段永平", "duanyongping"],
        "munger-poor-charlie": ["poor charlie", "munger", "charlie"],
        "relationships-school-of-life": ["relationships", "school of life"],
        "on-love-alain-de-botton": ["on love", "alain de botton"],
        "guide-to-good-life": ["guide to the good life", "stoic joy", "william irvine"],
        "slap-in-the-face": ["slap in the face", "insults", "why insults"],
        "thinking-fast-slow": ["thinking", "fast and slow", "kahneman"],
        "atomic-habits": ["atomic habits", "james clear", "habits"],
        "influence": ["influence", "cialdini"],
        "the-innovators-dilemma": ["innovator's dilemma", "innovators dilemma", "christensen"],
        "the-selfish-gene": ["selfish gene", "dawkins"],
        # ===== 新增 10 本书 =====
        "abundance": ["abundance", "future better than you think"],
        "how-to-create-chemistry": ["how to create chemistry", "chemistry with anyone"],
        "i-hear-you": ["i hear you"],
        "more-than-you-know": ["more than you know"],
        "sell-with-a-story": ["sell with a story", "paul smith"],
        "daodejing-survival": ["道德经", "无反馈期生存"],
        "money-mindset-prison": ["穷人富人", "中产的思维", "思维程序"],
        "how-to-get-lucky": ["how to get lucky"],
        "nick-zak-capitalism": ["nick and zak", "adventures in capitalism"],
        "think-twice": ["think twice"],
    }

    # ===== 领域集群 =====
    # 每个领域包含的 book_id 列表
    _domain_clusters = {
        "投资理财": [
            "duanyongping-investing", "munger-poor-charlie", "what-i-learned-from-darwin",
            "competition-demystified", "the-innovators-dilemma",
        ],
        "决策与认知": [
            "thinking-fast-slow", "munger-poor-charlie",
        ],
        "心理学与社会": [
            "thinking-fast-slow", "on-desire", "status-anxiety", "on-confidence",
            "slap-in-the-face", "influence", "the-selfish-gene",
        ],
        "人际关系": [
            "relationships-school-of-life", "on-love-alain-de-botton", "alison-rapport",
            "slap-in-the-face", "influence",
        ],
        "人生哲学": [
            "guide-to-good-life", "die-with-zero", "the-stoic-challenge", "status-anxiety",
        ],
        "习惯与行动": [
            "atomic-habits", "the-stoic-challenge",
        ],
    }

    # ===== 跨域关联 =====
    # 当主书被识别时，自动也从这些关联书中拉取内容
    # key: 主书 book_id, value: 关联的 book_id 列表
    _cross_ref_map = {
        # 投资 → 关联：认知偏误、欲望动机、社会地位、人性博弈
        "duanyongping-investing": [
            "thinking-fast-slow", "on-desire", "status-anxiety", "influence", "the-selfish-gene",
        ],
        "munger-poor-charlie": [
            "thinking-fast-slow", "on-desire", "status-anxiety", "the-selfish-gene",
        ],
        "what-i-learned-from-darwin": [
            "the-selfish-gene", "thinking-fast-slow", "competition-demystified",
        ],
        "competition-demystified": [
            "the-innovators-dilemma", "munger-poor-charlie", "the-selfish-gene",
        ],
        "the-innovators-dilemma": [
            "what-i-learned-from-darwin", "munger-poor-charlie",
        ],

        # 心理学 → 关联：投资（人性应用于市场）、行动方法
        "thinking-fast-slow": [
            "duanyongping-investing", "on-desire", "status-anxiety", "influence",
        ],
        "on-desire": [
            "status-anxiety", "thinking-fast-slow", "atomic-habits", "guide-to-good-life",
        ],
        "status-anxiety": [
            "on-desire", "on-confidence", "guide-to-good-life", "slap-in-the-face",
        ],
        "on-confidence": [
            "status-anxiety", "relationships-school-of-life", "the-stoic-challenge",
        ],

        # 人际关系 → 关联：心理、影响
        "relationships-school-of-life": [
            "on-love-alain-de-botton", "slap-in-the-face", "on-desire", "on-confidence",
        ],
        "alison-rapport": [
            "influence", "relationships-school-of-life", "on-confidence",
        ],

        # 人生哲学 → 关联：心理、欲望、身份
        "guide-to-good-life": [
            "the-stoic-challenge", "on-desire", "status-anxiety", "slap-in-the-face",
        ],
        "die-with-zero": [
            "on-desire", "status-anxiety", "guide-to-good-life",
        ],
        "the-stoic-challenge": [
            "guide-to-good-life", "on-desire", "slap-in-the-face",
        ],

        # 习惯 → 关联：心理、欲望
        "atomic-habits": [
            "thinking-fast-slow", "on-desire", "the-stoic-challenge",
        ],

        # 心流 → 关联：心理、欲望、行动
        "finding-flow": [
            "on-desire", "thinking-fast-slow", "atomic-habits", "guide-to-good-life",
        ],

        # 象与骑象人 → 关联：哲学、心理（最跨界的书）
        "the-happiness-hypothesis": [
            "guide-to-good-life", "on-desire", "status-anxiety",
            "thinking-fast-slow", "the-selfish-gene", "relationships-school-of-life",
        ],

        # 金钱心理学 / 一如既往 → 关联：投资、认知偏误、欲望
        "the-psychology-of-money": [
            "duanyongping-investing", "same-as-ever", "thinking-fast-slow",
            "on-desire", "status-anxiety",
        ],
        "same-as-ever": [
            "the-psychology-of-money", "duanyongping-investing", "thinking-fast-slow",
        ],

        # 超预测 → 关联：认知偏误、投资决策
        "superforecasting": [
            "thinking-fast-slow", "munger-poor-charlie", "what-i-learned-from-darwin",
        ],

        # 助推 → 关联：行为经济学、习惯、影响力
        "nudge": [
            "thinking-fast-slow", "atomic-habits", "influence", "on-desire",
        ],

        # 睡眠、营养、抗炎 → 健康生活三角
        "why-we-sleep": [
            "thinking-fast-slow", "atomic-habits", "the-stoic-challenge",
        ],
        "spoon-fed": [
            "why-we-sleep", "anti-inflammation-life", "nudge",
        ],
        "anti-inflammation-life": [
            "why-we-sleep", "spoon-fed", "atomic-habits",
        ],

        # 活出生命的意义 → 关联：存在哲学、斯多葛
        "mans-search-for-meaning": [
            "guide-to-good-life", "the-stoic-challenge", "die-with-zero",
            "status-anxiety", "on-desire",
        ],

        # 斯多葛三书互相强关联 + 各配心理视角
        "meditations": [
            "guide-to-good-life", "the-stoic-challenge", "on-the-shortness-of-life",
            "the-enchiridion", "status-anxiety", "slap-in-the-face",
        ],
        "on-the-shortness-of-life": [
            "guide-to-good-life", "the-stoic-challenge", "meditations",
            "die-with-zero", "status-anxiety",
        ],
        "the-enchiridion": [
            "guide-to-good-life", "the-stoic-challenge", "meditations",
            "on-desire", "slap-in-the-face",
        ],
    }

    def get_cross_refs(self, book_id: str) -> list[str]:
        """获取某本书的关联书列表"""
        return self._cross_ref_map.get(book_id, [])

    def get_book_title(self, book_id: str) -> str:
        """获取 book_id 对应的中文书名"""
        for bid, title in self.books:
            if bid == book_id:
                return title
        return book_id

    def _discover_books(self) -> list[tuple[str, str]]:
        """自动发现所有书籍，去重合并 skill + EPUB"""
        from collections import OrderedDict

        books = OrderedDict()  # book_id -> title

        # 1. 扫描 skills → 有 chapters/ + SKILL.md 的
        for entry in os.listdir(self.books_base):
            skill_md = os.path.join(self.books_base, entry, "SKILL.md")
            chapters = os.path.join(self.books_base, entry, "chapters")
            if os.path.isfile(skill_md) and os.path.isdir(chapters):
                title = self._skill_titles.get(entry, entry)
                books[entry] = title

        # 2. 扫描 EPUB/PDF，按 _skill_epub_map 合并到已有 skill 上
        for ext in ("*.epub", "*.pdf"):
            for fpath in sorted(glob.glob(os.path.join(self.epub_dir, ext))):
                fname_stem = os.path.splitext(os.path.basename(fpath))[0]
                fname_lower = fname_stem.lower()

                # 尝试匹配已有 skill
                matched = False
                for skill_id, keywords in self._skill_epub_map.items():
                    if any(kw.lower() in fname_lower for kw in keywords):
                        # 如果该 skill 已有书名，用 skill 的；否则用文件名
                        if skill_id not in books:
                            books[skill_id] = self._skill_titles.get(skill_id, fname_stem)
                        matched = True
                        break

                if not matched:
                    # 无匹配：自动生成 id
                    book_id = re.sub(r"[^a-z0-9\u4e00-\u9fff]", "-", fname_lower.replace(" ", "-")).strip("-")
                    if not book_id:
                        # 纯中文文件名，用哈希值
                        book_id = f"book_{hash(fname_stem) % 10**8}"
                    if book_id not in books:
                        books[book_id] = fname_stem

        return list(books.items())

    @property
    def books(self) -> list[tuple[str, str]]:
        return self._discover_books()


settings = Settings()
