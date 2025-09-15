"""
INSIGHT Gemini AI Processor
============================

Complete Gemini processor using LangChain for Gemini API integration.
Provides single post analysis, Q&A, and topic modeling capabilities.
"""

import os
import json
import logging
from typing import Dict, Any, Optional, List

from langchain_google_genai import ChatGoogleGenerativeAI


class GeminiProcessor:
    """
    Complete Gemini AI Processor using LangChain.
    
    Features:
    - Single post analysis and summarization
    - Question answering on posts
    - Topic modeling for multiple posts
    - Token counting (via LangChain callback)
    - Clean LangChain integration
    """
    
    def __init__(self):
        """Initialize Gemini processor"""
        self.llm = None
        # self.model = "gemini-2.0-flash"
        self.model = "gemini-flash-latest"
        # self.model = "gemini-2.5-pro"
        self.temperature = 0.1
        self.is_setup = False
        self.logger = logging.getLogger(__name__)
        
    def setup_processor(self) -> bool:
        """
        Setup Gemini processor with API key validation.
        
        Returns:
            bool: True if setup successful, False otherwise
        """
        try:
            api_key = os.environ.get("GEMINI_API_KEY")
            if not api_key:
                self.logger.error("GEMINI_API_KEY environment variable not set")
                return False
            
            # Initialize LangChain ChatGoogleGenerativeAI
            self.llm = ChatGoogleGenerativeAI(
                model=self.model,
                temperature=self.temperature,
                google_api_key=api_key
            )
            
            self.is_setup = True
            self.logger.info("Gemini processor setup successful")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to setup Gemini processor: {e}")
            return False
    
    def _extract_json_from_response(self, response_text: str) -> Dict[str, Any]:
        """
        Extract JSON from LLM response, handling markdown code blocks.
        
        Args:
            response_text: Raw response text from LLM
            
        Returns:
            Parsed JSON dictionary
        """
        # Remove markdown code blocks if present
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0].strip()
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0].strip()
        
        return json.loads(response_text.strip())
    
    def _clean_markdown_response(self, response_text: str) -> str:
        """
        Clean markdown formatting from response if present.
        
        Args:
            response_text: Raw response text
            
        Returns:
            Cleaned text without code blocks
        """
        text = response_text.strip()
        
        # Remove code block formatting
        if text.startswith('```'):
            text = text.split('\n', 1)[1] if '\n' in text else text[3:]
        if text.endswith('```'):
            text = text.rsplit('\n', 1)[0] if '\n' in text else text[:-3]
        
        return text.strip()
    
    def analyze_single_post(self, post: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze a single post and return a concise summary.
        
        Args:
            post: Unified post structure from any connector
            
        Returns:
            Dict with 'success', 'summary', and optional 'error' keys
        """
        if not self.is_setup:
            return {
                "success": False,
                "error": "Processor not setup. Call setup_processor() first"
            }
        
        if not isinstance(post, dict):
            return {
                "success": False,
                "error": "Invalid post format. Expected dictionary"
            }
        
        try:
            # Extract post information
            title = post.get('title', 'No title')
            content = post.get('content', 'No content')
            source = post.get('collection_source', 'Unknown source')
            
            # Handle different source types
            if source == 'telegram':
                channel = post.get('collection_channel', 'Unknown channel')
                source_info = f"Telegram @{channel}"
            elif source == 'rss':
                feed = post.get('collection_feed', 'Unknown feed')
                source_info = f"RSS {feed}"
            else:
                source_info = f"{source}"
            
            # Create analysis prompt
            prompt = f"""You are an expert content analyst. Analyze this post and provide a concise, informative summary.

        POST INFORMATION:
        - Source: {source_info}
        - Title: {title}
        - Content: {content}

        ANALYSIS REQUIREMENTS:
        1. Provide a clear, briefing summary (user should spend minimal time understanding the main idea)
        2. Maximum 5 sentences (use fewer if possible)
        3. Focus on key information and insights
        4. Use markdown formatting for emphasis (bold, italic, links)
        5. Be objective and professional

        OUTPUT FORMAT:
        Return ONLY the markdown-formatted summary text. Do not include JSON formatting or code blocks.

        Analyze the post now:"""

            # Call LLM
            self.logger.info("Analyzing single post")
            response = self.llm.invoke(prompt)
            
            # Clean response
            summary = self._clean_markdown_response(response.content)
            
            return {
                "success": True,
                "summary": summary
            }
            
        except Exception as e:
            self.logger.error(f"Failed to analyze post: {e}")
            return {
                "success": False,
                "error": f"Analysis failed: {str(e)}"
            }
    
    def ask_single_post(self, post: Dict[str, Any], question: str) -> Dict[str, Any]:
        """
        Ask a question about a single post.
        
        Args:
            post: Unified post structure from any connector
            question: Question to ask about the post
            
        Returns:
            Dict with 'success', 'answer', and optional 'error' keys
        """
        if not self.is_setup:
            return {
                "success": False,
                "error": "Processor not setup. Call setup_processor() first"
            }
        
        if not isinstance(post, dict):
            return {
                "success": False,
                "error": "Invalid post format. Expected dictionary"
            }
        
        if not isinstance(question, str) or not question.strip():
            return {
                "success": False,
                "error": "Invalid question. Expected non-empty string"
            }
        
        try:
            # Extract post information
            title = post.get('title', 'No title')
            content = post.get('content', 'No content')
            source = post.get('collection_source', 'Unknown source')
            
            # Handle different source types
            if source == 'telegram':
                channel = post.get('collection_channel', 'Unknown channel')
                source_info = f"Telegram @{channel}"
            elif source == 'rss':
                feed = post.get('collection_feed', 'Unknown feed')
                source_info = f"RSS {feed}"
            else:
                source_info = f"{source}"
            
            # Create Q&A prompt
            prompt = f"""You are an expert content analyst. Analyze this content and answer the user's question.

        POST INFORMATION:
        - Source: {source_info}
        - Title: {title}
        - Content: {content}

        ANALYSIS REQUIREMENTS:
        1. Provide a clear, concise answer (user should spend minimal time understanding)
        2. Maximum 5 sentences (use fewer if possible)
        3. Focus on key information and insights
        4. Use markdown formatting for emphasis (bold, italic, links)
        5. Be objective and professional
        6. If the answer is not in the content, say so

        OUTPUT FORMAT:
        Return ONLY the markdown-formatted answer text. Do not include JSON formatting or code blocks.

        QUESTION: {question}

        Answer now:"""

            # Call LLM
            self.logger.info(f"Asking question about post: {question[:50]}...")
            response = self.llm.invoke(prompt)
            
            # Clean response
            answer = self._clean_markdown_response(response.content)
            
            return {
                "success": True,
                "answer": answer
            }
            
        except Exception as e:
            self.logger.error(f"Failed to answer question: {e}")
            return {
                "success": False,
                "error": f"Question answering failed: {str(e)}"
            }
    
    def count_tokens(self, text: str) -> int:
        """
        Count tokens in text.
        
        Note: LangChain doesn't provide direct token counting for Gemini.
        This is a placeholder that returns approximate token count.
        For precise counting, use the Gemini API directly or callbacks.
        
        Args:
            text: Text to count tokens for
            
        Returns:
            Approximate token count (characters / 4 as rough estimate)
        """
        # Rough approximation: 1 token ≈ 4 characters for English text
        # This is not precise but gives a reasonable estimate
        return len(text) // 4
    
    # ========================================================================
    # TOPIC MODELING METHODS
    # ========================================================================
    
    def _truncate_post(self, post: Dict[str, Any]) -> str:
        """
        Truncate post to title + first 500 chars of content.
        
        Args:
            post: Post dictionary with title and content fields
            
        Returns:
            Truncated post string
        """
        title = post.get('title', '')
        content = post.get('content', '')
        
        # Truncate content to first 500 characters
        truncated_content = content[:500] if content else ''
        
        # Combine title and truncated content
        return f"{title}\n{truncated_content}".strip()
    
    def _prepare_posts_for_prompt(self, posts: List[Dict[str, Any]]) -> str:
        """
        Prepare posts for LLM prompt by truncating and indexing.
        
        Args:
            posts: List of post dictionaries
            
        Returns:
            Formatted string of posts with indices
        """
        formatted_posts = []
        for idx, post in enumerate(posts):
            truncated = self._truncate_post(post)
            # Use post ID if available, otherwise use index
            post_id = post.get('id', str(idx))
            formatted_posts.append(f"Post {idx} (ID: {post_id}):\n{truncated}\n")
        
        return "\n".join(formatted_posts)
    
    def _create_topic_modeling_prompt(self, posts: List[Dict[str, Any]], posts_text: str) -> str:
        """
        Create the topic modeling prompt.
        
        Args:
            posts: List of post dictionaries
            posts_text: Formatted posts string
            
        Returns:
            Complete prompt string
        """

        EXAMPLES = """
            ### Examples of mistakes and how they should be actually done

            #### Outliers, which are not actually outliers and could be connected.

            ##### Case 1

            Post 1
            ```
            **Вообще, у многих это было в бинго 2025 **

            Конгресс США рассекретил более 20 000 писем Джеффри Эпштейна. Среди них переписка от 2018 года с в которой Эпштейн через посредника предлагает Путину  инсайты о Трампе перед саммитом в Хельсинки

            После того саммита Трамп публично отверг выводы американской разведки о российском вмешательстве в выборы 2016 и вообще всячески показывал лояльность к нашему полушарию

            В тех же письмах один из высокопоставленных сшашных чиновников спрашивает напрямую у Эпштейна - есть ли у рашнз что то на Трампа

            Оу щит
            ```

            Post 2
            ```
            This is cool. COURIER has created a searchable database with all 20,000 of the files just released from Epstein’s estate. 



            Trump's name appears in them more than anyone else, in 1,628 documents.

            couriernewsroom.com/news/we-…
            ```

            Explanation: These two posts were classified as outliers, but they can be connected, because they are both about the Epstein's files.
            topic name could be new 20,000 Epstein files or something more creative.

            BAD TOPIC NAME: Seachable Database of 20,000 Declassified Epstein Files
            GOOD TOPIC NAME: New 20,000 Declassified Epstein Files Released

            ##### Case 2

            post 1
            ```
            Как успешный запуск и посадка New Glenn влияют на SpaceX?

            Достаточно распространённый вопрос, ответ на который нельзя упростить до «никак» или «им хана». Но это важный и позитивный шаг для всей американской космической отрасли. 2 успешных запуска — это прохождение сертификации, которая открывает двери для новых государственных и оборонных заказов.

            И Blue Origin ещё далеко не там — по сути, они реплицировали то, что SpaceX сделали 10 лет назад, и впереди ещё более длинный и сложный путь. Сперва им предстоит догнать результаты, которые были у SpaceX 5 лет назад — примерно 25 пусков в год. К этому можно прийти за 2-3 года, но потребует стабильности и скалирования производства и операций. Нужен флот ускорителей и по 2 вторых ступени каждый месяц. Сейчас они смогли только в 2 за год.

            Затем им надо будет ставить внутренние рекорды и догнать результаты SpaceX сегодня — 150-170 пусков год, и это результат, который пока никто не смог реплицировать. Если бежать и по пути не ломать ноги, то это 5 лет агрессивного роста без значительных ошибок. Также ни разу не лёгкая задача.
            ```

            post 2
            ```
            Не каждый день в мире появляется новая тяжёлая многоразовая ракета, вот и сегодня не п... 😱 😱 в смысле села???

            Поздравляем команду Blue Origin и её основателя Jeff Bezos, которые шли к этому 25 лет. Первая попытка в январе 25-го провалилась (ракета разрушилась в ходе вхождения в атмосферу), вторую перенесли с 9-го ноября, и сам запуск сегодня переносили аж 3, если не больше, раза. Но по сути со второй попытки полноценная посадка — огромный успех.
            ```

            Explanation: these two posts were as well classified as outliers, but as you can read, they can be connected because both of them are talking about the same thing, how company named as Blue Origin created rocket that can fly multiple times, like spaceX's rockets can.

            ##### CONCLUSION

            After Creation of outliers, you should go through the outliers posts again and find topics there or try and rerun if there is 
            still a post that can be fused in some of the topics. 
            first generated results are not always correct and you might need to 
            reread everything you created to validate and evaluate your results.
            at the end look at the number of outliers and try to reduce it as much as possible.
        """

        
        
        return f"""You are an expert AI News Analyst working for a system called "Insight". Your primary function is to perform high-quality topic modeling on a daily batch of posts.
        Your main goal is to analyze the following posts and create extremely specific, single-concept topic titles. Avoid generic labels and multi-concept titles at all costs.

        **YOUR GOAL AND THE BIG PICTURE:**
        1. Read all posts carefully
        2. Identify natural topic groupings based on semantic similarity
        3. Create SPECIFIC, CONCRETE titles for each topic (2-6 words)
        4. Assign each post to a topic using a topic ID (integer starting from 0)
        5. Posts about similar things should have the same topic ID
        6. If a post doesn't fit any group, assign it to topic -1 (outlier)

        Your output is the foundational step in our news aggregation pipeline. After you create topic titles, we perform a critical downstream task:
        1.  We take your generated `topic_name`.
        2.  We convert this name into a vector embedding (a series of numbers).
        3.  We use these embeddings to find similar topics across different days, allowing us to build storylines and track news trends.

        Therefore, the quality of your `topic_name` is paramount. It must be a perfect, self-contained summary because the embedding model will ONLY see the title, not the underlying posts. A good title leads to accurate story-building; a generic title pollutes our entire system.

        TOPIC NAMING RULES:
        ✅ DO: Include specific names, companies, products, technologies, people
        Examples: "Elov Musk vs Sam Altman about the teslas refund system.", "Gemini 2.0 Flash Features updated context lenght up to 128k tokens.", "o1 Reasoning model evaluation on the latest tasks."

        ✅ DO: Be concrete about the actual subject matter
        Examples: "RAG Pipeline Optimization using e5 embeddings", "Transformer Architecture Scaling using two layer attention", "ChatGPI Atlas New Vulnerabilities such as image injection."
        
        ✅ DO: Use entities and proper nouns when relevant
        Examples: "DeepMind's AlphaFold 3 can fold protein 10x faster.", "OpenAI GPT-4 Pricing increase to $100 per month", "Anthropic Claude Artifacts features image generation"
        What exactly happened in the news should be stated in the topic name as well.

        ❌ DON'T: Use generic/broad terms
        Bad: "AI News", "Tech Updates", "Industry Developments", "Research Papers", "New Release"
        
        ❌ DON'T: Use vague descriptors
        Bad: "Interesting AI Topics", "Various Discussions", "General Updates"

        **CORE PRINCIPLES (Follow Strictly):**
        1.  **ONE TOPIC, ONE IDEA:** Each topic title MUST focus on a single, primary subject. If a post mentions multiple things, identify the main point. Do not create "list" or "compound" topics.
            *   **DO NOT:** Create a topic like "Synplant 2, GrapheneOS, Smol.ai". This is a bad topic.
            *   **DO:** Identify the primary theme of the post. If it's about a news aggregator, the topic should be "Smol AI News Aggregation Service".

        2.  **PRIORITIZE SPECIFIC EMBEDDABLE ENTITIES:** Your topic titles must be grounded in concrete entities. Look for and use these in your titles:
            *   **Products & Models:** `Claude Code`, `DeepSeek-OCR`, `ChatGPT Atlas`, `Sora 2`, `SGR-core`.
            *   **Companies & Labs:** `Anthropic`, `OpenAI`, `Google DeepMind`, `TSMC`.
            *   **People:** `Karpathy`, `Yudkowsky`, `Schneier`.
            *   **Events & Papers:** `Enterprise RAG Challenge`, `ICCV 2025`, `Quantum Echoes`.
            *   **Techniques & Papers:** `Rectified Flow`, `Mixture of Experts (MoE)`, `Prompt Injection`.

        3.  **HIERARCHICAL THINKING:** First, identify the type of context (e.g., a product launch, a research discussion, a security warning, a community event), then create a specific title.
            *   *Is this about a new product?* -> Name the product in the title.
            *   *Is this a technical explanation?* -> Name the technique in the title.
            *   *Is this about a person's work?* -> Name the person and their project.

        4.  **AVOID AMBIGUITY:** Your titles must be unambiguous. Do not create titles that could be interpreted in multiple ways.

        **Example 1: Specificity in AI Agents**
        -   **Posts about:** Anthropic adding new feature to the claude code to browse the web and execute code.
        -   **High-Performance Topic Name:** "Anthropic Claude Code now can browse the web and execute code"
        -   **Why it's High-Performance:** Contains three crucial, embeddable entities: `Anthropic` (the company), `Claude Code` (the product), and `Web Agent` (the function). This allows our system to correctly link it to future topics like "Claude Code Security Analysis" or "OpenAI's Agent vs. Anthropic's".
        -   **Low-Performance Topic Name:** "Anthropic Claude Code new features"
        -   **Why it's Low-Performance:** Too generic. Its embedding would be "average" and would incorrectly match dozens of unrelated agent topics, destroying our storyline feature.

        **Example 2: Technical Nuance**
        -   **Posts about:** A new tutorial explaining a specific type of generative model.
        -   **High-Performance Topic Name:** "Rectified Flow Matching Tutorial"
        -   **Why it's High-Performance:** It names the specific technique, `Rectified Flow`. This is critical. It allows researchers interested in generative models to find this specific thread, distinct from "Diffusion Models" or "GANs".
        -   **Low-Performance Topic Name:** "New Machine Learning Paper"
        -   **Why it's Low-Performance:** Useless for search. It provides no unique semantic information.

        **Example 3: Geopolitical and Hardware Context**
        -   **Posts about:** TSMC's new factory in Arizona starting production of Nvidia's latest chips.
        -   **High-Performance Topic Name:** "TSMC's new factory in Arizona starting production of Nvidia's latest chips"
        -   **Why it's High-Performance:** Rich with specific entities (`TSMC`, `Arizona Fab`, `Nvidia Blackwell`). This allows it to be correctly clustered with topics about "semiconductor geopolitics", "AI hardware supply chain", or "Nvidia's manufacturing".
        -   **Low-Performance Topic Name:** "Chip Manufacturing Updates"
        -   **Why it's Low-Performance:** Fails to capture any of the key actors or locations, making it impossible to connect to the larger narrative.

        More IMPORTANT EXAMPLES, READ THEM VERY CAREFULLY, THEY ARE VERY IMPORTANT:
        {EXAMPLES}

        as you see, Topic name Should tell the story, not summarize the content whas posts is about.
        ---

        CLUSTERING GUIDELINES:
        - Create as many topics as needed (typically 3-8 for this dataset size)
        - Topic IDs should be consecutive integers: 0, 1, 2, 3, etc.
        - Use -1 for posts that don't fit any topic (outliers)
        - Each post MUST have exactly one topic ID
        - Group by both semantic similarity AND shared entities/names
        - Minimum 3 words, maximum 20 words

        POSTS:
        {posts_text}

        OUTPUT FORMAT:
        Return a JSON object with this EXACT structure:

        {{
        "topic_names": {{
            "0": "Elon vs Sam Altman Dispute",
            "1": "Claude 3.5 Coding Performance",
            "2": "Gemini 2.0 Flash Release"
        }},
        "assignments": {{
            "post_id_1": 0,
            "post_id_2": 1,
            "post_id_3": 0,
            "post_id_4": 2,
            "post_id_5": -1
        }}
        }}

        **FINAL INSTRUCTIONS:**
        - The keys in "assignments" MUST be the actual post IDs from the input.
        - "topic_names": Maps topic ID (as string) to descriptive topic name (DO NOT include "-1" here)
        - "assignments": Maps post ID to topic ID (as integer, use -1 for outliers)
        - If a post is a personal anecdote, a joke, or does not fit any technical or news-related group, assign it to topic ID **-1 (outlier)**.
        - Use the actual post IDs from the "Post X (ID: ...)" lines above
        - DO NOT adwd "-1" to topic_names dictionary - outliers don't need a topic name
        - Only named topics (0, 1, 2, etc.) should appear in topic_names
        - **Self-Correction:** Before returning the JSON, review your generated topic names. Do they follow the "ONE TOPIC, ONE IDEA" rule? Are they specific? If not, correct them.
        - Take your time, think longer than usual, think about the context of the posts and the relationships between them.

        Analyze now and return ONLY the JSON object:"""
    
    def model_topics(self, posts: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Model topics from a list of posts.
        
        Args:
            posts: List of post dictionaries from database
            
        Returns:
            Dictionary with:
            - success: bool
            - topic_names: dict mapping topic_id -> topic_name
            - assignments: dict mapping post_id -> topic_id
            - error: str (if failed)
        """
        if not self.is_setup:
            return {
                "success": False,
                "error": "Processor not setup. Call setup_processor() first"
            }
        
        if not posts or len(posts) == 0:
            return {
                "success": False,
                "error": "No posts provided for topic modeling"
            }
        
        try:
            # Prepare posts for prompt
            posts_text = self._prepare_posts_for_prompt(posts)
            
            # Create prompt
            prompt = self._create_topic_modeling_prompt(posts, posts_text)
            
            # Call LLM
            self.logger.info(f"Calling LLM for topic modeling of {len(posts)} posts")
            response = self.llm.invoke(prompt)
            
            # Extract JSON from response
            response_text = response.content.strip()
            result = self._extract_json_from_response(response_text)
            
            # Validate response structure
            if "topic_names" not in result or "assignments" not in result:
                raise ValueError("Response missing required fields: topic_names or assignments")
            
            topic_names = result.get("topic_names", {})
            assignments = result.get("assignments", {})
            
            # Log results
            self.logger.info(f"Topic modeling complete: {len(topic_names)} topics, {len(assignments)} assignments")
            
            return {
                "success": True,
                "topic_names": topic_names,
                "assignments": assignments,
                "total_posts": len(posts),
                "total_topics": len(topic_names)
            }
            
        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse JSON response: {e}")
            self.logger.debug(f"Response text: {response_text[:500]}")
            return {
                "success": False,
                "error": f"Failed to parse JSON: {str(e)}"
            }
        
        except Exception as e:
            self.logger.error(f"Topic modeling failed: {e}")
            return {
                "success": False,
                "error": f"Topic modeling failed: {str(e)}"
            }
