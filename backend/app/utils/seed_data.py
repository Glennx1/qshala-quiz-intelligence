import os
from pathlib import Path
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor

SEED_DIR = Path(__file__).resolve().parent.parent.parent / "sample_decks"
SEED_DIR.mkdir(parents=True, exist_ok=True)

def create_australian_history_deck() -> Path:
    prs = Presentation()
    prs.slide_width = Inches(10)
    prs.slide_height = Inches(5.625)

    blank_slide_layout = prs.slide_layouts[6]

    # Slide 1: Title Slide
    slide = prs.slides.add_slide(blank_slide_layout)
    txBox = slide.shapes.add_textbox(Inches(1), Inches(1.5), Inches(8), Inches(2))
    tf = txBox.text_frame
    p = tf.paragraphs[0]
    p.text = "QShala Quest: Australian History & Explorers"
    p.font.size = Pt(36)
    p.font.bold = True
    p.font.color.rgb = RGBColor(20, 40, 80)
    
    p2 = tf.add_paragraph()
    p2.text = "Curated Tournament Round for Grades 3 to 5 (Year: 2022)"
    p2.font.size = Pt(20)
    p2.font.color.rgb = RGBColor(100, 100, 100)

    # Q&A data
    qa_pairs = [
        (
            "Q1. Who was the British naval officer and navigator who mapped the eastern coastline of Australia aboard HMS Endeavour in 1770?",
            ["(A) Captain James Cook", "(B) Matthew Flinders", "(C) Arthur Phillip", "(D) William Bligh"],
            "Ans: (A) Captain James Cook",
            "Explanation: Captain James Cook charted Botany Bay and the east coast in 1770, claiming New South Wales for Britain aboard HMS Endeavour."
        ),
        (
            "Q2. What is the historic name given to the convoy of 11 British ships that arrived in Sydney Cove in January 1788 to establish the first European settlement?",
            ["(A) The Sovereign Fleet", "(B) The First Fleet", "(C) The Golden Armada", "(D) The Pacific Squadron"],
            "Ans: (B) The First Fleet",
            "Explanation: Commanded by Captain Arthur Phillip, the First Fleet carried over 1,400 convicts, marines, and officials, arriving on 26 January 1788."
        ),
        (
            "Q3. For tens of thousands of years before European arrival, Aboriginal Australians shared oral sacred creation stories known in English by what name?",
            ["(A) The Bush Songs", "(B) The Dreamtime (Jukurrpa)", "(C) The Outback Chronicles", "(D) The Coral Legends"],
            "Ans: (B) The Dreamtime (Jukurrpa)",
            "Explanation: The Dreamtime encompasses the ancient spiritual, cultural, and geographic history of the world created by Ancestral Beings."
        ),
        (
            "Q4. On January 1, 1901, the six colonies federated to form the Commonwealth of Australia. Who served as the nation's first Prime Minister?",
            ["(A) Sir Edmund Barton", "(B) Alfred Deakin", "(C) Henry Parkes", "(D) Andrew Fisher"],
            "Ans: (A) Sir Edmund Barton",
            "Explanation: Sir Edmund Barton was sworn in as Australia's inaugural Prime Minister at Centennial Park, Sydney on New Year's Day 1901."
        ),
        (
            "Q5. Why was the inland city of Canberra chosen as Australia's federal capital in 1913 instead of Sydney or Melbourne?",
            ["(A) It had the busiest harbor", "(B) As a compromise between rival cities Sydney and Melbourne", "(C) Because gold was found there in 1900", "(D) It was closest to the Great Barrier Reef"],
            "Ans: (B) As a compromise between rival cities Sydney and Melbourne",
            "Explanation: The Australian Constitution required a capital in NSW at least 100 miles from Sydney, choosing Canberra as a grand neutral compromise."
        ),
        (
            "Q6. Which legendary Australian bushranger and folk figure wore 44-kilogram homemade iron plate armor during his final standoff in Glenrowan in 1880?",
            ["(A) Ned Kelly", "(B) Ben Hall", "(C) Captain Starlight", "(D) Dan Morgan"],
            "Ans: (A) Ned Kelly",
            "Explanation: Ned Kelly and the Kelly Gang forged heavy protective suits from ploughshares before their famous 1880 siege."
        ),
        (
            "Q7. In 1854, gold prospectors in Ballarat, Victoria rose up against colonial mining licenses in which historic rebellion for democratic rights?",
            ["(A) The Rum Rebellion", "(B) The Eureka Stockade", "(C) The Castle Hill Uprising", "(D) The Bathurst Rebellion"],
            "Ans: (B) The Eureka Stockade",
            "Explanation: The Eureka Stockade was a pivotal rebellion where miners swore allegiance under the Southern Cross flag against injustice."
        ),
        (
            "Q8. Which aerodynamic wooden hunting and sport tool was developed by Indigenous Australians over tens of thousands of years and is famous for returning when thrown?",
            ["(A) Boomerang", "(B) Woomera", "(C) Didgeridoo", "(D) Coolamon"],
            "Ans: (A) Boomerang",
            "Explanation: Indigenous Australians mastered aerodynamics, designing returning boomerangs for decoy hunting, ceremony, and game."
        ),
        (
            "Q9. What iconic sacred sandstone monolith in the Northern Territory desert was officially handed back to its traditional Anangu owners in October 1985?",
            ["(A) Kata Tjuta", "(B) Uluru (Ayers Rock)", "(C) Mount Kosciuszko", "(D) Wave Rock"],
            "Ans: (B) Uluru (Ayers Rock)",
            "Explanation: Uluru is deeply sacred to the Anangu people, who regained land title in a historic handback ceremony on 26 October 1985."
        ),
        (
            "Q10. In 1902, the Commonwealth Franchise Act made Australia one of the earliest modern nations to grant which democratic right to women nationally?",
            ["(A) The right to vote and stand for federal parliament", "(B) The right to captain sea ships", "(C) Free access to overseas travel", "(D) The right to own postal offices"],
            "Ans: (A) The right to vote and stand for federal parliament",
            "Explanation: Australia granted women the federal right to vote and run for parliament in 1902, following South Australia's pioneering 1894 act."
        )
    ]

    for q_text, opts, ans_text, expl_text in qa_pairs:
        # Question Slide
        slide_q = prs.slides.add_slide(blank_slide_layout)
        tb_q = slide_q.shapes.add_textbox(Inches(0.8), Inches(0.8), Inches(8.4), Inches(4))
        tf_q = tb_q.text_frame
        tf_q.word_wrap = True
        
        p = tf_q.paragraphs[0]
        p.text = q_text
        p.font.size = Pt(22)
        p.font.bold = True
        p.font.color.rgb = RGBColor(30, 30, 30)

        for opt in opts:
            p_opt = tf_q.add_paragraph()
            p_opt.text = opt
            p_opt.font.size = Pt(18)
            p_opt.font.color.rgb = RGBColor(60, 60, 60)

        # Answer Slide
        slide_a = prs.slides.add_slide(blank_slide_layout)
        tb_a = slide_a.shapes.add_textbox(Inches(0.8), Inches(1.2), Inches(8.4), Inches(3.5))
        tf_a = tb_a.text_frame
        tf_a.word_wrap = True

        p_ans = tf_a.paragraphs[0]
        p_ans.text = ans_text
        p_ans.font.size = Pt(26)
        p_ans.font.bold = True
        p_ans.font.color.rgb = RGBColor(0, 128, 64)

        p_expl = tf_a.add_paragraph()
        p_expl.text = expl_text
        p_expl.font.size = Pt(18)
        p_expl.font.color.rgb = RGBColor(50, 50, 50)

    target_path = SEED_DIR / "Australian_History_Quiz_2022.pptx"
    prs.save(target_path)
    return target_path

def create_world_geography_deck() -> Path:
    prs = Presentation()
    prs.slide_width = Inches(10)
    prs.slide_height = Inches(5.625)
    blank_layout = prs.slide_layouts[6]

    slide = prs.slides.add_slide(blank_layout)
    tb = slide.shapes.add_textbox(Inches(1), Inches(1.5), Inches(8), Inches(2))
    tf = tb.text_frame
    p = tf.paragraphs[0]
    p.text = "QShala Junior Explorers: World Wonders & Oceans"
    p.font.size = Pt(36)
    p.font.bold = True

    qa_list = [
        (
            "Q1. Which Australian coral reef system is recognized as the largest living structure on Planet Earth and can be seen from space?",
            ["(A) Belize Barrier Reef", "(B) The Great Barrier Reef", "(C) Red Sea Coral Reef", "(D) New Caledonia Barrier Reef"],
            "Ans: (B) The Great Barrier Reef",
            "Explanation: Spanning over 2,300 kilometers off the Queensland coast, the Great Barrier Reef is composed of billions of tiny coral polyps."
        ),
        (
            "Q2. Which mountain in the Himalayas is the highest peak above sea level on Earth at 8,848.86 meters?",
            ["(A) K2", "(B) Mount Everest", "(C) Kangchenjunga", "(D) Lhotse"],
            "Ans: (B) Mount Everest",
            "Explanation: Mount Everest, called Sagarmatha in Nepal and Chomolungma in Tibet, stands on the border between Nepal and China."
        )
    ]

    for q_text, opts, ans, expl in qa_list:
        slide_q = prs.slides.add_slide(blank_layout)
        tb_q = slide_q.shapes.add_textbox(Inches(0.8), Inches(0.8), Inches(8.4), Inches(4))
        tf_q = tb_q.text_frame
        p = tf_q.paragraphs[0]
        p.text = q_text
        p.font.size = Pt(22)
        p.font.bold = True
        for o in opts:
            po = tf_q.add_paragraph()
            po.text = o
            po.font.size = Pt(18)

        slide_a = prs.slides.add_slide(blank_layout)
        tb_a = slide_a.shapes.add_textbox(Inches(0.8), Inches(1.2), Inches(8.4), Inches(3.5))
        tf_a = tb_a.text_frame
        pa = tf_a.paragraphs[0]
        pa.text = ans
        pa.font.size = Pt(26)
        pa.font.bold = True
        pe = tf_a.add_paragraph()
        pe.text = expl
        pe.font.size = Pt(18)

    target_path = SEED_DIR / "World_Geography_and_Oceans_2023.pptx"
    prs.save(target_path)
    return target_path

if __name__ == "__main__":
    p1 = create_australian_history_deck()
    p2 = create_world_geography_deck()
    print(f"Generated sample decks:\n - {p1}\n - {p2}")
