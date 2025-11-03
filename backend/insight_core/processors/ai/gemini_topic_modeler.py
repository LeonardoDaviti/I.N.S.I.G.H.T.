"""
INSIGHT Topic Modeling Processor
=================================

Simple LLM-based topic modeling for daily posts using Google Gemini via Langchain.
Groups posts into coherent topics and returns topic names + assignments.
"""

import os
import json
import logging
from typing import Dict, Any, List

from langchain_google_genai import ChatGoogleGenerativeAI


class GeminiTopicModeler:
    """
    Simple topic modeling processor using Google Gemini via Langchain.
    
    Features:
    - Groups daily posts into semantic topics
    - Returns topic names and post-to-topic assignments
    - Truncates posts to reduce token usage
    - Uses Langchain for clean API integration
    """
    
    def __init__(self):
        """Initialize the topic modeler"""
        self.llm = None
        self.model =  "gemini-flash-latest" # "gemini-2.0-flash"
        self.temperature = 0.1
        self.is_setup = False
        self.logger = logging.getLogger(__name__)
        
    def setup_processor(self) -> bool:
        """
        Setup the topic modeler with API key validation.
        
        Returns:
            bool: True if setup successful, False otherwise
        """
        try:
            api_key = os.environ.get("GEMINI_API_KEY")
            if not api_key:
                self.logger.error("GEMINI_API_KEY environment variable not set")
                return False
            
            # Initialize Langchain ChatGoogleGenerativeAI
            self.llm = ChatGoogleGenerativeAI(
                model=self.model,
                temperature=self.temperature,
                google_api_key=api_key
            )
            
            self.is_setup = True
            self.logger.info("Topic modeler setup successful")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to setup topic modeler: {e}")
            return False
    
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
    
    def _create_prompt(self, posts: List[Dict[str, Any]], posts_text: str) -> str:
        """
        Create the topic modeling prompt.
        
        Args:
            posts: List of post dictionaries
            posts_text: Formatted posts string
            
        Returns:
            Complete prompt string
        """
        return f"""You are a topic modeling expert. Analyze these {len(posts)} posts and group them into coherent topics.

TASK:
1. Read all posts carefully
2. Identify natural topic groupings based on semantic similarity
3. Create SPECIFIC, CONCRETE titles for each topic (2-6 words)
4. Assign each post to a topic using a topic ID (integer starting from 0)
5. Posts about similar things should have the same topic ID
6. If a post doesn't fit any group, assign it to topic -1 (outlier)

TOPIC NAMING RULES:
✅ DO: Include specific names, companies, products, technologies, people
   Examples: "Elon vs Sam Altman Drama", "Gemini 2.0 Flash Features", "o1 Reasoning Model Benchmarks"
   
✅ DO: Be concrete about the actual subject matter
   Examples: "RAG Pipeline Optimization", "Transformer Architecture Scaling", "LLM Security Vulnerabilities"
   
✅ DO: Use entities and proper nouns when relevant
   Examples: "DeepMind's AlphaFold 3", "OpenAI GPT-4 Pricing", "Anthropic Claude Artifacts"
   
❌ DON'T: Use generic/broad terms
   Bad: "AI News", "Tech Updates", "Industry Developments", "Research Papers"
   
❌ DON'T: Use vague descriptors
   Bad: "Interesting AI Topics", "Various Discussions", "General Updates"

CLUSTERING GUIDELINES:
- Create as many topics as needed (typically 3-8 for this dataset size)
- Topic IDs should be consecutive integers: 0, 1, 2, 3, etc.
- Use -1 for posts that don't fit any topic (outliers)
- Each post MUST have exactly one topic ID
- Group by both semantic similarity AND shared entities/names

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
    "post_id_4": 2
  }}
}}

Where:
- "topic_names": Maps topic ID (as string) to descriptive topic name
- "assignments": Maps post ID to topic ID (as integer)

IMPORTANT: Use the actual post IDs from the "Post X (ID: ...)" lines above.

Analyze now and return ONLY the JSON object:"""
    
    def _extract_json_from_response(self, response_text: str) -> Dict[str, Any]:
        """
        Extract JSON from LLM response, handling code blocks.
        
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
        
        # Parse JSON
        return json.loads(response_text.strip())
    
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
                "error": "Topic modeler not setup. Call setup_processor() first"
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
            prompt = self._create_prompt(posts, posts_text)
            
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

