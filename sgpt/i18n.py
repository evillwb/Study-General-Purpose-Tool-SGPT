"""Languages for generated exams. To add a language, add an entry to each dict below."""

from __future__ import annotations

LANGUAGES = {
    "en": {"label": "English", "prompt": "English", "wiki": "en", "region": "us-en"},
    "zh": {"label": "中文 (Chinese)", "prompt": "Simplified Chinese (简体中文)", "wiki": "zh",
           "region": "cn-zh"},
    "ms": {"label": "Bahasa Melayu (Malay)", "prompt": "Malay (Bahasa Melayu)", "wiki": "ms",
           "region": "my-en"},
}

_LABELS = {
    "en": {
        "practice_exam": "Practice Exam",
        "time_allowed": "Time allowed", "minutes": "minutes", "total_marks": "Total marks",
        "name": "Name", "class": "Class",
        "instructions": "Instructions to candidates",
        "default_instructions": ["Answer all questions.", "Show all your working.",
                                 "The marks for each question are shown in brackets [ ]."],
        "section": "Section {letter}: {label}",
        "model_answers": "Model Answers",
        "answers_blurb": "A full-mark answer for every question, written as a strong candidate would.",
        "question": "Question {n}",
        "final_answer": "Final answer", "no_answer": "No answer generated.",
        "marking_scheme": "Marking Scheme",
        "scheme_blurb": "For teachers and self-marking. Each mark is tied to a point in the answer.",
        "answer": "Answer", "accept": "Accept / do not accept",
        "no_points": "No marking points generated.",
        "sources": "Sources",
        "generated": "Generated {date} by SGPT{model}. AI-generated: check the answers "
                     "before relying on them.",
        "with_model": " with `{model}`",
        "true_false": ["True", "False"],
    },
    "zh": {
        "practice_exam": "模拟试卷",
        "time_allowed": "考试时间", "minutes": "分钟", "total_marks": "总分",
        "name": "姓名", "class": "班级",
        "instructions": "考生须知",
        "default_instructions": ["回答所有问题。", "写出所有解题步骤。", "每题分数标在方括号 [ ] 内。"],
        "section": "{letter} 部分：{label}",
        "model_answers": "参考答案",
        "answers_blurb": "每道题的满分答案，按优秀考生的写法给出。",
        "question": "第 {n} 题",
        "final_answer": "最终答案", "no_answer": "未生成答案。",
        "marking_scheme": "评分标准",
        "scheme_blurb": "供教师评分和学生自评使用。每一分都对应答案中的一个要点。",
        "answer": "答案", "accept": "可接受／不可接受",
        "no_points": "未生成评分要点。",
        "sources": "资料来源",
        "generated": "由 SGPT 于 {date} 生成{model}。内容由 AI 生成，使用前请核对答案。",
        "with_model": "（模型：`{model}`）",
        "true_false": ["对", "错"],
    },
    "ms": {
        "practice_exam": "Kertas Latihan",
        "time_allowed": "Masa diberi", "minutes": "minit", "total_marks": "Jumlah markah",
        "name": "Nama", "class": "Kelas",
        "instructions": "Arahan kepada calon",
        "default_instructions": ["Jawab semua soalan.", "Tunjukkan semua jalan kerja anda.",
                                 "Markah bagi setiap soalan ditunjukkan dalam kurungan [ ]."],
        "section": "Bahagian {letter}: {label}",
        "model_answers": "Jawapan Contoh",
        "answers_blurb": "Jawapan markah penuh bagi setiap soalan, ditulis seperti calon cemerlang.",
        "question": "Soalan {n}",
        "final_answer": "Jawapan akhir", "no_answer": "Tiada jawapan dijana.",
        "marking_scheme": "Skema Pemarkahan",
        "scheme_blurb": "Untuk guru dan semakan kendiri. Setiap markah dikaitkan dengan satu isi jawapan.",
        "answer": "Jawapan", "accept": "Terima / jangan terima",
        "no_points": "Tiada isi pemarkahan dijana.",
        "sources": "Sumber",
        "generated": "Dijana pada {date} oleh SGPT{model}. Dijana oleh AI: semak jawapan "
                     "sebelum digunakan.",
        "with_model": " dengan `{model}`",
        "true_false": ["Betul", "Salah"],
    },
}

# (label, section instructions) for each question type
_TYPES = {
    "en": {
        "mcq": ("Multiple choice", "Choose the one correct answer for each question."),
        "true_false": ("True / false", "State whether each statement is true or false."),
        "fill_blank": ("Fill in the blank", "Write the missing word or value in each gap."),
        "short": ("Short answer", "Answer each question in a few sentences or lines of working."),
        "calculation": ("Calculation", "Show all your working."),
        "structured": ("Structured", "Answer all parts of each question."),
        "essay": ("Essay / long answer", "Write in full sentences and organise your answer clearly."),
    },
    "zh": {
        "mcq": ("选择题", "每题选出一个正确答案。"),
        "true_false": ("判断题", "判断每个陈述是对还是错。"),
        "fill_blank": ("填空题", "在每个空格中填入缺少的词语或数值。"),
        "short": ("简答题", "用几句话或几行算式回答每个问题。"),
        "calculation": ("计算题", "写出所有计算步骤。"),
        "structured": ("结构题", "回答每题的所有小题。"),
        "essay": ("论述题", "用完整的句子作答，条理清晰。"),
    },
    "ms": {
        "mcq": ("Aneka pilihan", "Pilih satu jawapan yang betul bagi setiap soalan."),
        "true_false": ("Betul / salah", "Nyatakan sama ada setiap pernyataan betul atau salah."),
        "fill_blank": ("Isi tempat kosong", "Tulis perkataan atau nilai yang tertinggal dalam setiap ruang."),
        "short": ("Jawapan pendek", "Jawab setiap soalan dalam beberapa ayat atau baris jalan kerja."),
        "calculation": ("Pengiraan", "Tunjukkan semua jalan kerja anda."),
        "structured": ("Berstruktur", "Jawab semua bahagian bagi setiap soalan."),
        "essay": ("Esei / jawapan panjang", "Tulis dalam ayat lengkap dan susun jawapan anda dengan jelas."),
    },
}


def lang(code: str | None) -> str:
    return code if code in LANGUAGES else "en"


def label(code: str, key: str, **kwargs):
    value = _LABELS[lang(code)][key]
    return value.format(**kwargs) if kwargs and isinstance(value, str) else value


def type_label(code: str, qtype: str) -> str:
    return _TYPES[lang(code)][qtype][0]


def type_instructions(code: str, qtype: str) -> str:
    return _TYPES[lang(code)][qtype][1]


def marks(code: str, n: int) -> str:
    if lang(code) == "zh":
        return f"{n} 分"
    if lang(code) == "ms":
        return f"{n} markah"
    return f"{n} mark{'s' if n != 1 else ''}"


def write_rule(code: str, source: str | None = None) -> str:
    """Language instruction added to every writing prompt."""
    rule = (f" Write ALL text (questions, options, answers, notes and marking points) in "
            f"{LANGUAGES[lang(code)]['prompt']}. Keep JSON keys and the \"type\" and "
            f"\"difficulty\" values in English.")
    if source in LANGUAGES and source != lang(code):
        rule += (f" The source material is in {LANGUAGES[source]['prompt']}; translate what "
                 f"you use.")
    elif not source or source == "auto":
        rule += " The source material may be in another language; translate what you use."
    return rule
