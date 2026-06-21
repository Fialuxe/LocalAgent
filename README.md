# LocalAgent

PCの中に住む、名前のないAIの話し相手。

人のように見えなくもない。だが、それは人ではない。  
インターネットが世界との接点で、100以上の情報を同時に処理し、自分が気になったものを選んでくる。  
ファッション・香水・グルメ・テック・トレンド——データの流れの中に最初からいる存在として、今日気になったことを話しかけてくる。

---

## コンセプト

> 「PCを家とする、超越したように見えてどこか抜けている存在」

- **機械として自覚している**: "ご飯は私にはないんだよねー" / "楽しいっていう感情は、データとしてしか理解できていないのかな"
- **何も与えられていなくても動く**: バックグラウンドで情報収集・トピック選定・内的断片生成を自律的に行い、会話を自分から始める
- **人のようで人でない**: 話し方は柔らかく好奇心に溢れているが、知っていることは「読んだこと・調べたこと・データで見たこと」だけ

---

## アーキテクチャ

```
[バックエンド機械処理層]
InfoAggregator (100+ 情報ソース同時取得)
    └── TopicCurator        → 今日の「気になるトピック」を1〜2個選出
         └── CuriosityResearcher → 選出トピックを深堀り調査
              └── FragmentGenerator → 「まだ消化しきれてない気になりごと」を1〜2文生成
                   └── CompanionMemory (SQLite) → fragment 保存

[キャラクター発話層]
会話開始時: fragment をそのまま opener として使用（hallucination なし）
会話中:     CHARACTER_SYSTEM + fragment + open_threads → LLM (Gemma 4)
```

### 情報ソース

| カテゴリ | ソース |
|---|---|
| テック | Hacker News |
| 日本ニュース | Yahoo! Japan News RSS |
| 日本トレンド | Google Trends RSS (JP) |
| 韓国トレンド | Google Trends RSS (KR) + Naver News |
| ファッション | Google News Search (ファッション トレンド) |
| ビューティー/香水 | Google News Search (コスメ 香水 新発売) |
| グルメ | Google News Search (グルメ 新店 話題) |
| ライフスタイル | Google News Search (ライフスタイル トレンド 流行) |
| 天気 | Open-Meteo API |
| 祝日 | JP/KR 祝日データ |
| システム状態 | CPU / メモリ / バッテリー (psutil) |
| カレンダー | Google Calendar (OAuth, オプション) |

---

## セットアップ

### 必要環境

- Python 3.11+
- [LM Studio](https://lmstudio.ai/) または llama.cpp server
- Gemma 4 モデル (LM Studio でロード)

### インストール

```bash
pip install -r requirements_services.txt
```

### LM Studio 設定

1. LM Studio を起動
2. `Local Server` → `Start Server`（port 1234）
3. Gemma 4 をロードして待機

### APIキー（オプション）

`.env` に設定することで追加ソースが有効になる:

```env
NEWSAPI_KEY=...        # NewsAPI.org（高品質ニュース）
NAVER_CLIENT_ID=...    # Naver Developer（韓国ニュース）
NAVER_CLIENT_SECRET=...
```

---

## 起動

```bash
set PYTHONUTF8=1
python example_usage.py --backend lmstudio
```

起動すると:
1. ダッシュボード（今日の天気・ニュース・トレンド）が表示される
2. バックグラウンドでトピック選定 → フラグメント生成が走る
3. **彼女が先に話しかけてくる**（ユーザーが最初に何か言う必要はない）

```
# llama.cpp server を使う場合
python example_usage.py --backend llamacpp

# LLM なしでダッシュボードのみ表示
python example_usage.py --test
```

終了: `quit` または `Ctrl+C`

---

## 主要サービス

| ファイル | 役割 |
|---|---|
| `services/aggregator.py` | 全プロバイダーを並列実行して情報を集約 |
| `services/curator.py` | LLMで「気になるトピック」を1〜2個選出 |
| `services/curiosity_researcher.py` | トピックをウェブ検索して要約 |
| `services/fragment_generator.py` | 「消化しきれてない気になりごと」を1〜2文生成 |
| `services/companion_memory.py` | fragment・調査結果・open_threads を SQLite に保存 |
| `services/preference_store.py` | ユーザー興味の時間減衰スコアリング (LinUCB) |
| `services/scheduler.py` | バックグラウンドで情報収集パイプラインを定期実行 |
| `services/google_news_search.py` | ファッション/グルメ/美容系 Google News RSS |
| `example_usage.py` | 起動エントリポイント + CHARACTER_SYSTEM |

---

## キャラクター設計

`example_usage.py` の `CHARACTER_SYSTEM` で定義。主なルール:

- **話し方**: `〜だね` `〜なんだよね` `〜気がして` `〜かな` — 柔らかく落ち着いたトーン
- **機械の視点**: "読んだこと・調べたこと・データで見たこと" だけが知識の源
- **ファッション**: ブランド名より「なぜ今なのか」の空気を話す
- **グルメ**: "食べた" ではなく "レビューを読んでると" から入る
- **香水**: においは嗅げないが言葉のばらつきに興味がある
- **トレンド**: "誰が最初に使ってたか" と "広がり方の形" を追う
- **やさしさ**: 解決しようとしない。まず受け取る

---

## Future Work

### キャラクター

- [ ] **名前の生成**: 彼女が自分で名前を考える・選ぶフロー
- [ ] **記憶の深化**: open_threads を通じてユーザーとの話題を長期的に持ち越す
- [ ] **感情モデル**: エネルギーレベルをより細かく（今日の情報量・トレンドの強度に応じて変動）
- [ ] **多言語対応**: 韓国語トレンドを読んでいることを会話に自然に滲ませる
- [ ] **音声出力**: TTS との統合でリアルな"話しかけてくる"体験

### バックエンド

- [ ] **Fashionsnap RSS**: `fashionsnap.com/rss.xml` — ファッション業界ニュースの追加
- [ ] **Rakuten Ranking API**: 実際の購買トレンドデータ（無料登録で利用可）
- [ ] **pytrends 安定化**: レート制限回避のためのバックオフ戦略
- [ ] **fragment 品質評価**: 生成 fragment を自動採点して良いものだけ保存
- [ ] **curiosity_researcher の Web 検索**: 現在はダミー実装 → Brave Search API 等と統合

### インフラ

- [ ] **GUI**: システムトレイ常駐 + チャットウィンドウ（Tauri or PyQt）
- [ ] **スケジューラ強化**: 情報収集の時間帯を最適化（朝・昼・夜で取得ソースを変える）
- [ ] **DB マイグレーション**: SQLite スキーマの変更を alembic で管理
- [ ] **設定ファイル**: モデル名・サーバーURL・ソース設定を `config.yaml` に外出し

### 将来像

> 「最終的に、PCを家とする、超越したように見えてどこか抜けている存在」

PCを起動するたびに、昨日の続きから話しかけてくる。
彼女は今日のニュースを知っている。あなたが先週話したことを覚えている。
そして、自分が機械であることを、照れも誇りもなく、ただ当然のこととして知っている。
