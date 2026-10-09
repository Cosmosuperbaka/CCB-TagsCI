import os
import json
import hashlib
import logging
import datetime
from typing import Dict, List, Any, Tuple, Optional

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class UserTagProcessor:
    def __init__(self, mongo_uri: str = None, db_name: str = 'tags'):
        if mongo_uri is None:
            mongo_uri = os.environ.get('MONGODB_URI')
        self.mongo_uri = mongo_uri
        self.db_name = db_name
        self.client = None
        self.db = None

        self.conv = {
            '茶色瞳': '棕瞳',
            '中二': '中二病',
            '单马尾': '马尾',
            '渐变发': '渐变色发',
            '白发': '银发',
            'tv': 'TV',
            '偶像': '偶像(萌属性)',
        }

        self.hair_color_attr = [
            "黑发", "金发", "蓝发", "棕发", "银发",
            "红发", "紫发", "橙发", "绿发", "粉发",
        ]

        self.eye_color_attr = [
            "黑瞳", "金瞳", "蓝瞳", "棕瞳", "灰瞳", "红瞳",
            "紫瞳", "橙瞳", "绿瞳", "粉瞳", "白瞳",
        ]

        # Priority attributes for sorting final tags
        priority_attrs_raw = [
            "渐变瞳", "彩虹瞳", "异色瞳", "挑染", "双色发", "彩虹发", "多色发", "阴阳发",
            "光头", "黑瞳", "金瞳", "蓝瞳", "棕瞳", "灰瞳", "红瞳", "紫瞳", "橙瞳", "绿瞳",
            "粉瞳", "白瞳", "黑发", "金发", "蓝发", "棕发", "银发", "红发", "紫发", "橙发",
            "绿发", "粉发",
        ]
        self.priority_attrs = {}
        for idx, i in enumerate(priority_attrs_raw):
            self.priority_attrs[i] = (len(priority_attrs_raw) - idx) * 1000000

        # Load attr2char for sorting weight calculation
        file_dir = os.path.dirname(os.path.abspath(__file__))
        self.project_root = os.path.dirname(file_dir)
        attr2char_path = os.path.join(self.project_root, 'character_tags_crawler', 'moegirl', 'preprocess', 'attr2char.json')
        self.attr2char = {}
        if os.path.exists(attr2char_path):
            try:
                with open(attr2char_path, 'r', encoding='utf-8') as f:
                    self.attr2char = json.load(f)
            except Exception as e:
                logger.warning(f"Could not load attr2char.json for sorting weight: {e}")

        # Static blacklist for filtering out work-level and generic meta/VA/company tags
        self.blacklist_tags = {
            # Media formats & adaptation tags
            'TV', 'tv', 'OVA', 'ova', 'SP', 'sp', 'OAD', 'oad', 'Web', 'web', '劇場版', '剧场版',
            '游戏改', '漫画改', '小说改', '轻小说改', '漫改', '原创', '游改', '动画改', '广播剧', '真人改',
            '手改', '轻改', '手游', '单机', '网游', '网文改', '科幻改', '奇幻改', '电影', '动画', '游戏',
            # Genre / Theme tags (not specific to character features/personality)
            '校园', '校园风', '恋爱', '百合', '后宫', '日常', '奇幻', '科幻', '悬疑', '热血', '战斗', '音乐', '乐队',
            '赛博朋克', '搞笑', '运动', '治愈', '致郁', '推理', '社畜', '骨科', '乙女', '纯爱', '异世界',
            '转生', '轮回', '催泪', '搞笑向', '热血向', '战斗系', '百合向', '后宫向', '治愈系', '日常向',
            '致郁系', '冒险', '后宫漫', '日常漫', '校园向', '校园漫', '恋爱漫',
            # Studios / Publishers / Brands
            '京阿尼', '芳文社', '米哈游', 'mihoyo', 'miHoYo', 'Mihoyo', 'Cygames', 'Key', '型月',
            'Type-Moon', '吉卜力', '东映', '日升', '骨头社', 'Ufotable', 'MAPPA', 'A-1', 'J.C.STAFF',
            'Shaft', '京都动画', '芳文', 'mappa', 'bilibili', 'Bilibili', 'B站', '腾讯', '网易',
            '角川', '集英社', '讲谈社', '小学馆', 'SQUARE ENIX', 'Square Enix', 'CAPCOM', 'Capcom',
            '任天堂', 'Nintendo', '索尼', 'Sony', 'SEGA', 'Sega', 'Bandai', '万代', '科乐美',
            'Konami', '光荣', 'Koei', 'Atlus', '阿特拉斯', '企鹅物流', '花咲川', '礼园女子学院',
            # People (VAs, Authors, Directors, etc.)
            '高桥李依', '羊宫妃那', '子安武人', '花江夏树', '小原好美', '早见沙织', '平野绫',
            '松冈祯丞', '本渡枫', '佐仓绫音', '悠木碧', '花泽香菜', '水濑祈', '内田真礼', '雨宫天',
            '陈睿', '新海诚', '赤坂明', '花田十辉', '庵野秀明', '宫崎骏', '富坚义博', '鸟山明',
            '尾田荣一郎', '岸本齐史', '久保带人', '荒川弘', '藤本树', '石田翠', '谏山创',
            # Country / Region names
            '日本', '中国', '美国', '英国', '法国', '德国', '俄罗斯', '意大利', '西班牙', '韩国',
            '加拿大', '澳大利亚', '欧洲', '亚洲', '美洲',
            # Extremely generic / non-descriptive / meta / joke / crude tags
            '女性', '男性', '女', '男', '角色', '主角', '配角', '配音', 'CV', 'cv', '声优', '作品',
            '动漫', '二次元', '属性', '萌属性', '标签', '人物', '人类', '非人', '非人类', '可爱',
            '帅气', '漂亮', '好人', '坏人', '主角光环', '型月知名女演员', '魔法使之夜', '哈基米',
            '出生', '拉屎', '澡堂', '畜生', '标子', '手冲', '维尼', '小孩', '小孩姐', '那种事情不要啊',
            '4K', 'jump', 'JUMP', '单行本', '连载', '完结', '咕咕嘎嘎'
        }

    def connect(self) -> bool:
        if not self.mongo_uri:
            logger.warning("MONGODB_URI is not set. Cannot connect to MongoDB.")
            return False
        
        try:
            from pymongo import MongoClient
            if self.client is None:
                self.client = MongoClient(self.mongo_uri, serverSelectionTimeoutMS=5000)
                self.db = self.client[self.db_name]
                # Test connection
                self.client.admin.command('ping')
            return True
        except ImportError:
            logger.warning("pymongo package is not installed. MongoDB connection is disabled.")
            return False
        except Exception as e:
            logger.warning(f"Failed to connect to MongoDB: {e}")
            self.client = None
            self.db = None
            return False

    def close(self):
        if self.client is not None:
            self.client.close()
            self.client = None
            self.db = None

    def _parse_raw_documents(self, documents: List[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
        parsed = {}
        for doc in documents:
            char_id = str(doc['_id'])
            tag_counts = doc.get('tagCounts', {})
            normalized_tags = {}
            for k, v in tag_counts.items():
                if k in self.conv:
                    k = self.conv[k]
                normalized_tags[k] = v
            parsed[char_id] = normalized_tags
        return parsed

    def load_feedback_data(self, local_fallback_dir: str = None) -> Tuple[Dict[str, Dict[str, int]], Dict[str, Dict[str, int]]]:
        """Loads character_tags and new_tags from MongoDB, or falls back to local JSON files."""
        character_tags = {}
        new_tags = {}

        if self.connect():
            try:
                logger.info("Loading character_tags and new_tags from MongoDB...")
                
                # Fetch character_tags
                char_tags_raw = list(self.db['character_tags'].find())
                character_tags = self._parse_raw_documents(char_tags_raw)
                logger.info(f"Loaded {len(character_tags)} entries from character_tags.")

                # Fetch new_tags
                new_tags_raw = list(self.db['new_tags'].find())
                new_tags = self._parse_raw_documents(new_tags_raw)
                logger.info(f"Loaded {len(new_tags)} entries from new_tags.")

                self.close()
                return character_tags, new_tags
            except Exception as e:
                logger.error(f"Error loading from MongoDB: {e}. Falling back to local files.")
                self.close()

        # Fallback 1: Try ref/ CSV files (exported from MongoDB)
        ref_dir = os.path.join(self.project_root, 'ref')
        char_csv_path = os.path.normpath(os.path.join(ref_dir, 'character_tags.csv'))
        new_csv_path = os.path.normpath(os.path.join(ref_dir, 'new_tags.csv'))

        if os.path.exists(char_csv_path) or os.path.exists(new_csv_path):
            import csv
            logger.info("Local fallback: Loading feedback data from ref/*.csv files...")
            
            if os.path.exists(char_csv_path):
                try:
                    with open(char_csv_path, 'r', encoding='utf-8') as f:
                        reader = csv.reader(f)
                        next(reader) # skip header
                        csv_docs = []
                        for row in reader:
                            if len(row) >= 2:
                                csv_docs.append({
                                    '_id': row[0],
                                    'tagCounts': json.loads(row[1])
                                })
                        character_tags = self._parse_raw_documents(csv_docs)
                    logger.info(f"Loaded {len(character_tags)} entries from {char_csv_path}.")
                except Exception as e:
                    logger.error(f"Error loading character_tags CSV: {e}")
            
            if os.path.exists(new_csv_path):
                try:
                    with open(new_csv_path, 'r', encoding='utf-8') as f:
                        reader = csv.reader(f)
                        next(reader) # skip header
                        csv_docs = []
                        for row in reader:
                            if len(row) >= 2:
                                csv_docs.append({
                                    '_id': row[0],
                                    'tagCounts': json.loads(row[1])
                                })
                        new_tags = self._parse_raw_documents(csv_docs)
                    logger.info(f"Loaded {len(new_tags)} entries from {new_csv_path}.")
                except Exception as e:
                    logger.error(f"Error loading new_tags CSV: {e}")
                    
            if character_tags or new_tags:
                return character_tags, new_tags

        # Fallback 2: Local JSON files
        if local_fallback_dir and os.path.exists(local_fallback_dir):
            char_tags_path = os.path.join(local_fallback_dir, 'tags.character_tags.json')
            new_tags_path = os.path.join(local_fallback_dir, 'tags.new_tags.json')

            if os.path.exists(char_tags_path):
                logger.info(f"Loading character_tags from local file: {char_tags_path}")
                try:
                    with open(char_tags_path, 'r', encoding='utf-8') as f:
                        character_tags = self._parse_raw_documents(json.load(f))
                except Exception as e:
                    logger.error(f"Error loading local character_tags: {e}")

            if os.path.exists(new_tags_path):
                logger.info(f"Loading new_tags from local file: {new_tags_path}")
                try:
                    with open(new_tags_path, 'r', encoding='utf-8') as f:
                        new_tags = self._parse_raw_documents(json.load(f))
                except Exception as e:
                    logger.error(f"Error loading local new_tags: {e}")
        else:
            logger.warning(f"Fallback directory not found or not provided: {local_fallback_dir}")

        return character_tags, new_tags

    def parse_js_id_tags(self, js_path: str) -> Dict[str, List[str]]:
        if not os.path.exists(js_path):
            logger.warning(f"Existing JS file not found at {js_path}")
            return {}
        
        try:
            with open(js_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            import re
            match = re.search(r'idToTags\s*=\s*\{(.*?)\};', content, re.DOTALL)
            if not match:
                match = re.search(r'idToTags\s*=\s*\{(.*?)\}', content, re.DOTALL)
            if not match:
                logger.warning("Could not find idToTags object in JS content")
                return {}
                
            body = match.group(1)
            existing_tags = {}
            for item in re.finditer(r'(\d+)\s*:\s*\[(.*?)\]', body):
                char_id = item.group(1)
                tags_str = item.group(2)
                tags = []
                if tags_str.strip():
                    tags = [t.strip(' "\'') for t in tags_str.split(',')]
                    tags = [t for t in tags if t]
                existing_tags[char_id] = tags
            logger.info(f"Loaded {len(existing_tags)} characters from existing JS file.")
            return existing_tags
        except Exception as e:
            logger.error(f"Error parsing existing JS file: {e}")
            return {}

    def parse_js_id_tags_from_history(self, js_path: str) -> Dict[str, List[str]]:
        if not os.path.exists(js_path):
            logger.warning(f"Existing JS file not found at {js_path}")
            return {}
            
        # Try reading the current file first
        existing_tags = self.parse_js_id_tags(js_path)
        if len(existing_tags) > 31000:
            logger.info(f"Current JS file contains complete tag set ({len(existing_tags)} characters). Using it directly.")
            return existing_tags
            
        # If current file has fewer characters (e.g. due to previous failed run), walk back git history
        logger.info("Current JS file appears incomplete. Walking back git history of the file...")
        import subprocess
        try:
            repo_dir = os.path.normpath(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(js_path)))))
            relative_file_path = os.path.relpath(js_path, repo_dir).replace('\\', '/')
            logger.info(f"Checking history for file: {relative_file_path} in repo: {repo_dir}")
            
            commits_raw = subprocess.check_output(
                ["git", "log", "--format=%H", "--", relative_file_path],
                cwd=repo_dir,
                text=True,
                encoding='utf-8'
            )
            commits = [c.strip() for c in commits_raw.strip().split('\n') if c.strip()]
            
            for commit in commits:
                logger.info(f"Checking commit {commit} for complete tag set...")
                content = subprocess.check_output(
                    ["git", "show", f"{commit}:{relative_file_path}"],
                    cwd=repo_dir,
                    text=True,
                    encoding='utf-8'
                )
                
                # Parse the file content from this commit
                tags = {}
                import re
                match = re.search(r'idToTags\s*=\s*\{(.*?)\};', content, re.DOTALL)
                if not match:
                    match = re.search(r'idToTags\s*=\s*\{(.*?)\}', content, re.DOTALL)
                if match:
                    body = match.group(1)
                    for item in re.finditer(r'(\d+)\s*:\s*\[(.*?)\]', body):
                        char_id = item.group(1)
                        tags_str = item.group(2)
                        tags_lst = []
                        if tags_str.strip():
                            tags_lst = [t.strip(' "\'') for t in tags_str.split(',')]
                            tags_lst = [t for t in tags_lst if t]
                        tags[char_id] = tags_lst
                        
                if len(tags) > 31000:
                    logger.info(f"Found complete tag set ({len(tags)} characters) in commit {commit}!")
                    return tags
                    
        except Exception as e:
            logger.error(f"Error walking back git history of JS file: {e}")
            
        # Fallback to current if history retrieval fails
        return existing_tags

    def merge_user(self, bgmid: str, tags: List[str], user_tags: Dict[str, int]) -> List[str]:
        multicolor_hair = False

        merged_tags = tags + list(
            map(lambda x: x[0], filter(lambda x: x[1] > 1, user_tags.items()))
        )
        if (
            '双色发' in merged_tags
            or '渐变色发' in merged_tags
            or '彩虹发' in merged_tags
            or '多色发' in merged_tags
            or '阴阳发' in merged_tags
            or '挑染' in merged_tags
            or '内层挑染' in merged_tags
            or '变发色' in merged_tags
        ):
            multicolor_hair = True

        multicolor_eye = False
        if '异色瞳' in merged_tags or '渐变瞳' in merged_tags or '彩虹瞳' in merged_tags:
            multicolor_eye = True

        d = {}
        d_hair = {}
        d_eye = {}
        for tag in tags:
            if tag in self.hair_color_attr:
                d_hair[tag] = 4
            elif tag in self.eye_color_attr:
                d_eye[tag] = 4
            else:
                d[tag] = 4

        original_hair = list(d_hair.keys())
        original_eye = list(d_eye.keys())

        for tag, count in user_tags.items():
            if count <= 1:
                continue
            if tag in self.hair_color_attr:
                d_hair[tag] = d_hair.get(tag, 0) + count
            elif tag in self.eye_color_attr:
                d_eye[tag] = d_eye.get(tag, 0) + count
            else:
                d[tag] = d.get(tag, 0) + count

        if ('长发' in d or '长直' in d or '黑长直' in d) and '短发' in d:
            lmax = max(d.get('长发', 0), d.get('长直', 0), d.get('黑长直', 0))
            smax = d.get('短发', 0)
            if lmax == smax:
                pass
            elif lmax > smax:
                del d['短发']
            else:
                if '长发' in d:
                    del d['长发']
                if '长直' in d:
                    del d['长直']
                if '黑长直' in d:
                    del d['黑长直']

        ret = []
        for tag, count in d.items():
            if count >= 2:
                ret.append(tag)

        d_hair = sorted(
            filter(lambda x: x[1] > 1, list(d_hair.items())),
            key=lambda x: x[1],
            reverse=True,
        )
        d_eye = sorted(
            filter(lambda x: x[1] > 1, list(d_eye.items())),
            key=lambda x: x[1],
            reverse=True,
        )

        ret_hair = original_hair.copy()
        if multicolor_hair:
            if len(d_hair) < 2:
                pass
            elif len(d_hair) == 2:
                ret_hair = [d_hair[0][0], d_hair[1][0]]
            else:
                if d_hair[1][1] >= d_hair[2][1] * 2:
                    ret_hair = [d_hair[0][0], d_hair[1][0]]
        else:
            if len(d_hair) < 1:
                pass
            elif len(d_hair) == 1:
                ret_hair = [d_hair[0][0]]
            else:
                if d_hair[0][1] >= d_hair[1][1] * 2:
                    ret_hair = [d_hair[0][0]]

        ret_eye = original_eye.copy()
        if multicolor_eye:
            if len(d_eye) < 2:
                pass
            elif len(d_eye) == 2:
                ret_eye = [d_eye[0][0], d_eye[1][0]]
            else:
                if d_eye[1][1] >= d_eye[2][1] * 2:
                    ret_eye = [d_eye[0][0], d_eye[1][0]]
        else:
            if len(d_eye) < 1:
                pass
            elif len(d_eye) == 1:
                ret_eye = [d_eye[0][0]]
            else:
                if d_eye[0][1] >= d_eye[1][1] * 2:
                    ret_eye = [d_eye[0][0]]

        ret = ret_hair + ret_eye + ret
        return ret

    def value_func(self, x: str) -> int:
        if x in self.priority_attrs:
            return self.priority_attrs[x] * 100000
        if x in self.attr2char:
            return len(self.attr2char[x])
        return 0

    def merge_and_save(self, base_tags_path: str, 
                       character_tags: Dict[str, Dict[str, int]], 
                       new_tags: Dict[str, Dict[str, int]], 
                       output_js_path: str,
                       existing_js_path: str = None):
        logger.info(f"Loading base tags from {base_tags_path}...")
        with open(base_tags_path, 'r', encoding='utf-8') as f:
            original_tags = json.load(f)

        # Load existing JS tags as fallback for missing characters (walk git history if current file is incomplete)
        existing_tags = {}
        if existing_js_path and os.path.exists(existing_js_path):
            logger.info(f"Loading existing JS tags from {existing_js_path} as fallback...")
            existing_tags = self.parse_js_id_tags_from_history(existing_js_path)

        # Merge base tags and existing tags (retaining characters not in original_tags)
        merged_base_tags = original_tags.copy()
        fallback_count = 0
        for bgmid, tags in existing_tags.items():
            if bgmid not in merged_base_tags:
                merged_base_tags[bgmid] = tags
                fallback_count += 1
        logger.info(f"Added {fallback_count} character(s) from existing JS tags as fallback.")

        merged_tags = {}
        for bgmid, tags in merged_base_tags.items():
            char_feedback = character_tags.get(bgmid, {})
            char_proposals = new_tags.get(bgmid, {})

            # Calculate popularity-based dynamic threshold ratio
            # Determine the maximum positive vote count of any tag on this character
            max_single_vote = 0
            for tag, count in char_feedback.items():
                if count > max_single_vote:
                    max_single_vote = count
            for tag, count in char_proposals.items():
                if count > max_single_vote:
                    max_single_vote = count

            # Dynamic threshold limit (at least 3 for proposals, at least 2 for votes)
            proposal_thresh = max(3, int(max_single_vote * 0.15))
            vote_thresh = max(2, int(max_single_vote * 0.15))

            # 1. Process proposals from new_tags (requires count >= proposal_thresh and not blacklisted)
            accepted_proposals = {
                tag: count for tag, count in char_proposals.items()
                if count >= proposal_thresh and tag not in self.blacklist_tags and tag.strip()
            }

            # 2. Process votes from character_tags
            # - count >= vote_thresh: keep and strengthen (will pass to merge_user)
            # - count <= -2: players strongly disagree -> add to blacklist
            positive_votes = {
                tag: count for tag, count in char_feedback.items()
                if count >= vote_thresh and tag not in self.blacklist_tags and tag.strip()
            }
            blacklisted_tags = {tag for tag, count in char_feedback.items() if count <= -2}

            # Combine positive contributions (proposals and feedback votes)
            positive_user_tags = {}
            for tag, count in positive_votes.items():
                positive_user_tags[tag] = positive_user_tags.get(tag, 0) + count
            for tag, count in accepted_proposals.items():
                positive_user_tags[tag] = positive_user_tags.get(tag, 0) + count

            # 3. Merge base tags with positive user tags
            # Also filter out any blacklisted tags from initial tags list
            clean_base_tags = [tag for tag in tags if tag not in self.blacklist_tags]
            if positive_user_tags:
                merged = self.merge_user(bgmid, clean_base_tags, positive_user_tags)
            else:
                merged = clean_base_tags.copy()

            # 4. Filter out any blacklisted (downvoted or global blacklist) tags
            optimized = [
                tag for tag in merged 
                if tag not in blacklisted_tags and tag not in self.blacklist_tags and tag.strip()
            ]

            # 5. Priority sort optimized tags
            optimized.sort(key=self.value_func, reverse=True)

            merged_tags[bgmid] = optimized

        # ---- 增量基线：在覆盖之前读上一版产物 ----
        # BakaGame 侧据此增量更新角色标签，不必因为一个标签变了就重建整个数据集。
        previous_tags: Dict[str, List[str]] = {}
        previous_sha = None
        if os.path.exists(output_js_path):
            with open(output_js_path, 'rb') as f:
                previous_sha = hashlib.sha256(f.read()).hexdigest()
            previous_tags = self.parse_js_id_tags(output_js_path)
            logger.info(f"增量基线：上一版 {len(previous_tags)} 个角色（sha256 {previous_sha[:12]}）")
        else:
            logger.info("增量基线：无上一版产物，本次 diff 会包含全部角色")

        # Ensure output directory exists
        os.makedirs(os.path.dirname(os.path.abspath(output_js_path)), exist_ok=True)

        logger.info(f"Saving optimized JS to {output_js_path}...")
        with open(output_js_path, "w", encoding='utf-8') as f:
            f.write('export const idToTags = {\n')
            tags_js_lines = []
            for k, v in merged_tags.items():
                tags_js_lines.append((k, ':[' + ','.join(map(lambda x: f'"{x}"', v)) + ']'))
            tags_js_lines.sort(key=lambda x: int(x[0]))
            f.write(',\n'.join(map(lambda x: str(x[0]) + x[1], tags_js_lines)))
            f.write('\n};')

        self._write_diff(previous_tags, previous_sha, merged_tags, output_js_path)
        logger.info("Merging and optimization completed successfully.")

    def _write_diff(self, previous_tags: Dict[str, List[str]], previous_sha: Optional[str],
                    merged_tags: Dict[str, List[str]], output_js_path: str) -> None:
        """输出 `id_tags.diff.json`：只含相对上一版有变化的角色。

        BakaGame 的应用方要拿 `baseSha256` 与自己记录的版本比对：不一致说明中间漏了几轮，
        此时不能应用（会漏掉变更），应回退到拉全量。`removed` 是上一版有、这一版没有的角色。
        """
        with open(output_js_path, 'rb') as f:
            target_sha = hashlib.sha256(f.read()).hexdigest()

        added = {k: v for k, v in merged_tags.items() if k not in previous_tags}
        changed = {k: v for k, v in merged_tags.items()
                   if k in previous_tags and previous_tags[k] != v}
        removed = [k for k in previous_tags if k not in merged_tags]

        diff_path = os.path.join(os.path.dirname(os.path.abspath(output_js_path)), 'id_tags.diff.json')
        payload = {
            'generatedAt': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'baseSha256': previous_sha,
            'targetSha256': target_sha,
            'counts': {'total': len(merged_tags), 'added': len(added),
                       'changed': len(changed), 'removed': len(removed)},
            'added': added,
            'changed': changed,
            'removed': removed,
        }
        # 不缩进：diff 会被后端定期拉取，省下的字节比可读性值钱。
        with open(diff_path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, separators=(',', ':'))
        logger.info(f"增量：新增 {len(added)} / 变更 {len(changed)} / 移除 {len(removed)}"
                    f"（共 {len(merged_tags)} 角色）-> {diff_path}")
