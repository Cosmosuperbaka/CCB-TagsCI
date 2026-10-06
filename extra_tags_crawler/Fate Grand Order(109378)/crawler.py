import os
import sys
import re
import csv
import shutil
import json
import urllib.parse
from pathlib import Path
from bs4 import BeautifulSoup

# 将项目根目录添加到 sys.path 中，以便能够导入项目中的通用模块
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(project_root))

from character_tags_crawler.utils.network import safe_soup
from character_tags_crawler.utils.file import save_json_pretty

# 全局配置
FGO_ID = "109378"

# 相对工作区路径的定义
TAGSCI_WORKSPACE = project_root
GUESSER_WORKSPACE = project_root.parent / "anime-character-guessr"

OUTPUT_JSON_DIR = TAGSCI_WORKSPACE / "outputs" / "extra_tags"
OUTPUT_ASSETS_DIR = TAGSCI_WORKSPACE / "outputs" / "assets" / "extra_tags"

def crawl_bangumi_characters(subject_id: str):
    """
    爬取 Bangumi 上的角色列表，返回角色 ID 与中日文名字之间的映射关系。
    如果获取角色专属子页面失败，将尝试从主页面爬取作为后备逻辑。
    """
    print(f"[{subject_id}] 正在爬取 Bangumi 角色列表...")
    url = f"https://bgm.tv/subject/{subject_id}/characters"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    
    try:
        soup = safe_soup(url, headers=headers, cooldown=2)
    except Exception as e:
        print(f"警告: 无法获取角色子页面列表，正在尝试从主页面进行解析。错误信息: {e}")
        main_url = f"https://bgm.tv/subject/{subject_id}"
        soup = safe_soup(main_url, headers=headers, cooldown=2)

    id_name_mapping = {}
    for subtitle in soup.select("div.item h2.subtitle"):
        anchor = subtitle.find("a", href=re.compile(r"^/character/\d+"))
        if not anchor:
            continue

        match = re.search(r"/character/(\d+)", anchor["href"])
        if not match:
            continue

        character_id = match.group(1)
        name = anchor.get_text(strip=True)
        
        chinese_span = subtitle.find("span", class_="tip")
        chinese_name = chinese_span.get_text(strip=True) if chinese_span else ""
        
        id_name_mapping[character_id] = {
            "name": name,
            "chinese_name": chinese_name
        }
    
    print(f"[{subject_id}] 在 Bangumi 上找到了 {len(id_name_mapping)} 个角色。")
    return id_name_mapping

def process_fgo():
    """
    爬取FGO从者及标签核心逻辑：
    1. 爬取 Bangumi 的角色列表。
    2. 爬取 FGO Bwiki 英灵图鉴页面，解析包含 override_data 和 raw_str 的 JavaScript 块。
    3. 解析 override_data 获取从者中文名称；解析 raw_str CSV 获取稀有度、职阶、NP宝具、阵营及善恶秩序等属性。
    4. 将 Bangumi 角色与 Bwiki 从者进行匹配对齐 (利用括注、圆点和拼写归一化匹配，并对同名从者进行属性合并)。
    5. 复制本地已有的职阶卡、宝具卡与稀有度星级图标到输出文件夹。
    6. 生成最终的 JSON 文件，并将图片引用路径更改为 /assets/extra_tags/109378/...
    """
    # 1. 爬取 Bangumi 角色数据
    bgm_characters = crawl_bangumi_characters(FGO_ID)
    
    # 2. 爬取 FGO Bwiki
    print("[FGO] 正在抓取 FGO Bwiki 英灵图鉴页面...")
    bwiki_url = "https://fgo.wiki/w/%E8%8B%B1%E7%81%B5%E5%9B%BE%E9%89%B4"
    headers = {"User-Agent": "Mozilla/5.0"}
    soup = safe_soup(bwiki_url, headers=headers, cooldown=2)
    
    scripts = soup.find_all("script")
    fgo_script = None
    for script in scripts:
        text = script.string
        if text and ("raw_str" in text or "override_data" in text):
            fgo_script = text
            break
            
    if not fgo_script:
        print("错误: 未能在 FGO Bwiki 页面中找到包含数据的 script 块！")
        return
        
    # 提取 override_data 并清洗
    start_idx = fgo_script.find("override_data =")
    end_idx = fgo_script.find("function get_csv()")
    if start_idx == -1 or end_idx == -1:
        print("错误: 未能找到 override_data 或 get_csv() 的定位索引！")
        return
        
    override_block = fgo_script[start_idx:end_idx]
    first_quote = override_block.find('"')
    last_quote = override_block.rfind('"')
    override_str = override_block[first_quote+1:last_quote]
    override_clean = override_str.replace('\\n', '\n').replace(r'\n', '\n')
    
    # 解析 override_data 获取 ID 到名字信息的映射
    wiki_names = {}
    blocks = override_clean.strip().split('\n\n')
    for block in blocks:
        lines = block.strip().split('\n')
        info = {}
        for line in lines:
            if '=' in line:
                k, v = line.split('=', 1)
                info[k.strip()] = v.strip()
        if info.get("id"):
            wiki_names[info["id"]] = info
            
    print(f"[FGO] 解析 override_data 获取了 {len(wiki_names)} 个从者的名字信息。")

    # 提取 raw_str 并解析 CSV
    raw_str_match = re.search(r"raw_str\s*=\s*(['\"`])(.*?)\1", fgo_script, re.DOTALL)
    if not raw_str_match:
        print("错误: 未能提取出 raw_str CSV 数据！")
        return
        
    raw_str = raw_str_match.group(2)
    raw_str_clean = raw_str.replace('\\n', '\n').replace(r'\n', '\n')
    
    # 解析 CSV 行
    csv_rows = list(csv.DictReader(raw_str_clean.strip().splitlines()))
    print(f"[FGO] 解析 raw_str CSV 获取了 {len(csv_rows)} 个从者的数据行。")

    # 合并数据
    wiki_servants = {}
    for row in csv_rows:
        svt_id = row.get("id")
        if not svt_id or svt_id not in wiki_names:
            continue
            
        name_info = wiki_names[svt_id]
        name_cn = name_info.get("name_cn", "").strip()
        name_link = name_info.get("name_link", "").strip()
        
        # 稀有度
        rarity = f"{row['star']}星"
        
        # 属性 (包括善恶秩序和天人地星兽)
        alignments = []
        try:
            prop1 = int(row.get("prop1_marker", "0"))
            if prop1 & 1: alignments.append("秩序")
            if prop1 & 2: alignments.append("中立")
            if prop1 & 4: alignments.append("混沌")
        except ValueError:
            pass
            
        try:
            prop2 = int(row.get("prop2_marker", "0"))
            if prop2 & 1: alignments.append("善")
            if prop2 & 2: alignments.append("中庸")
            if prop2 & 4: alignments.append("恶")
        except ValueError:
            pass
            
        # 阵营 (天地人星兽)
        faction_raw = row.get("faction", "")
        factions = [f.strip() for f in faction_raw.split("&") if f.strip()]
        alignments.extend(factions)
        
        # 职阶名称和职阶卡文件名 (如 "金卡Saber.png")
        class_link = row.get("class_link", "").strip()
        class_icon_url = row.get("class_icon", "")
        class_icon_file = urllib.parse.unquote(class_icon_url.split("/")[-1]) if class_icon_url else f"金卡{class_link}.png"
        
        # 宝具类型 (如 Arts / Buster / Quick) 和宝具目标 (全体/单体/辅助)
        np_card_url = row.get("np_card", "")
        np_card_type = "Buster"
        if np_card_url:
            np_filename = np_card_url.split("/")[-1]
            np_card_type = np_filename.split(".")[0].strip()
        np_type = row.get("np_type", "全体").strip()
        
        servant_info = {
            "name_cn": name_cn,
            "name_link": name_link,
            "rarity": rarity,
            "alignments": alignments,
            "class_link": class_link,
            "class_icon_file": class_icon_file,
            "np_card_type": np_card_type,
            "np_type": np_type
        }
        
        # 以中文名和链接名为键存入映射中
        for key in [name_cn, name_link]:
            if not key:
                continue
            if key not in wiki_servants:
                wiki_servants[key] = [servant_info]
            else:
                wiki_servants[key].append(servant_info)

    # 3. 匹配 Bangumi 角色并对齐
    def normalize_brackets(s):
        if not s:
            return ""
        s = s.replace("〔", "(").replace("〕", ")")
        s = s.replace("[", "(").replace("]", ")")
        s = s.replace("（", "(").replace("）", ")")
        s = s.replace("・", "·")
        return s.strip()

    # 构建归一化命名映射表，方便进行容错匹配
    wiki_norm_map = {}
    for name, s_list in wiki_servants.items():
        wiki_norm_map[normalize_brackets(name)] = s_list

    # 4. 匹配 Bangumi 角色并筛选需要下载的素材
    matched_servants_by_cid = {}
    referenced_icons = set()
    for cid, info in bgm_characters.items():
        zh = info["chinese_name"]
        ja = info["name"]
        
        matched_servants = None
        for candidate in [zh, ja]:
            if not candidate:
                continue
            norm_candidate = normalize_brackets(candidate)
            if norm_candidate in wiki_norm_map:
                matched_servants = wiki_norm_map[norm_candidate]
                break
                
        if matched_servants:
            matched_servants_by_cid[cid] = matched_servants
            for s in matched_servants:
                referenced_icons.add(f"{s['rarity']}.png")
                referenced_icons.add(s["class_icon_file"])
                referenced_icons.add(f"{s['np_card_type']}.png")
                for align in s["alignments"]:
                    referenced_icons.add(f"{align}.png")

    # 自动下载缺失的图片资产
    from character_tags_crawler.utils.network import download_bwiki_missing_assets
    api_url = "https://fgo.wiki/api.php"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://fgo.wiki/"
    }
    fgo_assets_dir = OUTPUT_ASSETS_DIR / FGO_ID
    
    missing_assets = {}
    for icon_name in referenced_icons:
        name = icon_name.rsplit(".", 1)[0]
        missing_assets[icon_name] = [
            f"File:图标-{name}.png",
            f"File:Logo-{name}.png",
            f"File:{name}.png",
            f"File:{name}级.png",
            f"File:{name}star.png",
            f"File:{name}星.png",
            f"File:职阶-{name}.png",
            f"File:配卡-{name}.png"
        ]
        
    download_bwiki_missing_assets(api_url, missing_assets, fgo_assets_dir, headers)

    # Helper functions for dynamic file existence checking
    def get_rarity_html(rarity):
        if (fgo_assets_dir / f"{rarity}.png").exists():
            return f"<img src='/assets/extra_tags/{FGO_ID}/{rarity}.png' alt='{rarity}' />"
        return rarity

    def get_class_html(class_link, class_icon_file):
        if (fgo_assets_dir / class_icon_file).exists():
            return f"<img src='/assets/extra_tags/{FGO_ID}/{class_icon_file}'/>{class_link}"
        return class_link

    def get_np_html(np_card_type, np_type):
        if (fgo_assets_dir / f"{np_card_type}.png").exists():
            return f"<img src='/assets/extra_tags/{FGO_ID}/{np_card_type}.png' alt='{np_card_type}'/>{np_type}"
        return np_type

    extra_tags = {}
    for cid, matched_servants in matched_servants_by_cid.items():
        info = bgm_characters[cid]
        zh = info["chinese_name"]
        ja = info["name"]
        # 初始化属性归口容器
        rarities_dict = {}
        aligns_dict = {}
        classes_dict = {}
        np_dict = {}
        
        for s in matched_servants:
            # 稀有度
            rarity = s["rarity"]
            rarities_dict[rarity] = get_rarity_html(rarity)
            
            # 秩序善恶与天地人星兽属性
            for align in s["alignments"]:
                aligns_dict[align] = align
                
            # 职阶 (如 Saber)
            class_link = s["class_link"]
            class_icon_file = s["class_icon_file"]
            classes_dict[class_link] = get_class_html(class_link, class_icon_file)
            
            # 宝具
            np_card_type = s["np_card_type"]
            np_type = s["np_type"]
            np_name = f"{np_card_type}{np_type}"
            np_dict[np_name] = get_np_html(np_card_type, np_type)
            
        extra_tags[cid] = {
            "_name": zh or ja,
            "稀有度": rarities_dict,
            "属性": aligns_dict,
            "职阶": classes_dict,
            "宝具": np_dict
        }

    # 5. 生成 JSON 输出文件
    OUTPUT_JSON_DIR.mkdir(parents=True, exist_ok=True)
    out_json_file = OUTPUT_JSON_DIR / f"{FGO_ID}.json"
    from character_tags_crawler.utils.file import merge_and_save_extra_tags
    merge_and_save_extra_tags(FGO_ID, extra_tags, str(out_json_file), str(GUESSER_WORKSPACE))
    print(f"[FGO] 成功写入 {len(extra_tags)} 个从者属性到 {out_json_file}")

def main():
    print("=== FGO Extra Tags 自动爬取与处理程序 ===")
    try:
        process_fgo()
    except Exception as e:
        print(f"执行FGO爬取时发生错误: {e}")
        raise
    print("=== 执行完毕 ===")

if __name__ == "__main__":
    main()
