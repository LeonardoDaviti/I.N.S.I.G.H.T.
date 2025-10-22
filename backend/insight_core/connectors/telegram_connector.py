import asyncio
import os
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Union
from telethon.sync import TelegramClient
from telethon.errors import FloodWaitError, ChannelInvalidError, ChannelPrivateError, UsernameInvalidError, UsernameNotOccupiedError, RPCError
from .base_connector import BaseConnector
from .tool_registry import expose_tool

class TelegramConnector(BaseConnector):
    """
    Telegram Connector
    
    - Telethon client management
    - Album synthesis (grouping related media posts)
    - Request throttling to avoid rate limits
    - Message processing and normalization
    
    """
    
    def __init__(self):
        """
        Create blank connector object.
        No credentials needed - setup_connector() handles that.
        """
        super().__init__("telegram")
        
        # Placeholder values - will be set in setup_connector()
        self.api_id = None
        self.api_hash = None
        self.session_file = None
        self.client = None
        
        # Rate limiting defaults
        self.request_counter = 0
        self.REQUEST_THRESHOLD = 10
        self.COOLDOWN_SECONDS = 18
        
        self.logger.info("TelegramConnector object created (pending setup)")
    
    async def throttle_if_needed(self):
        """
        Checks the request counter and pauses if the threshold is exceeded.
        """
        if self.request_counter >= self.REQUEST_THRESHOLD:
            self.logger.warning(
                f"Request threshold ({self.REQUEST_THRESHOLD}) reached. "
                f"Initiating {self.COOLDOWN_SECONDS}-second cooldown."
            )
            await asyncio.sleep(self.COOLDOWN_SECONDS)
            self.request_counter = 0
            self.logger.info("Cooldown complete. Resuming operations.")
        self.request_counter += 1

    
    def setup_connector(self) -> bool:
        """
        Phase 2: Load credentials and configure the connector.
        
        Returns:
            bool: True if setup was successful, False otherwise
        """
        try:
            self.logger.info("Setting up Telegram connector...")
            
            # Load required credentials from environment
            api_id = os.getenv('TELEGRAM_API_ID')
            api_hash = os.getenv('TELEGRAM_API_HASH')
            
            # Validate required credentials
            if not api_id:
                self.logger.error("❌ TELEGRAM_API_ID not found in environment variables")
                return False
            
            if not api_hash:
                self.logger.error("❌ TELEGRAM_API_HASH not found in environment variables")
                return False
            
            # Convert and validate API ID
            try:
                self.api_id = int(api_id)
            except ValueError:
                self.logger.error("❌ TELEGRAM_API_ID must be a valid integer")
                return False
            
            # Set up core configuration
            self.api_hash = api_hash
            
            connector_dir = os.path.dirname(os.path.abspath(__file__))
            backend_dir = os.path.dirname(os.path.dirname(connector_dir))
            self.session_file = os.path.join(backend_dir, 'insight_session')
            
            # # Load optional rate limiting configuration
            # try:
            #     self.REQUEST_THRESHOLD = int(os.getenv('TELEGRAM_REQUEST_THRESHOLD', '15'))
            #     self.COOLDOWN_SECONDS = int(os.getenv('TELEGRAM_COOLDOWN_SECONDS', '67'))
            # except ValueError:
            #     self.logger.warning("⚠️ Invalid rate limiting config, using defaults")
            #     self.REQUEST_THRESHOLD = 15
            #     self.COOLDOWN_SECONDS = 67
            
            self.logger.info("✅ Telegram connector setup successful")
            self.logger.info(f"   Session file: {self.session_file}")
            self.logger.info(f"   Rate limiting: {self.REQUEST_THRESHOLD} requests/{self.COOLDOWN_SECONDS}s")
            
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Failed to setup Telegram connector: {e}")
            return False
        
    
    async def connect(self) -> None:
        """
        Phase 3: Establish connection using configured credentials.
        """
        if not self.api_id or not self.api_hash:
            raise RuntimeError("Connector not properly setup - call setup_connector() first")
        
        self.client = TelegramClient(self.session_file, self.api_id, self.api_hash)
        self.logger.info("Connecting to Telegram...")
        
        await self.client.connect()
        
        if not await self.client.is_user_authorized():
            self.logger.warning("Client not authorized. Please follow prompts for first-time login.")
            phone = input("Enter your phone number: ")
            await self.client.send_code_request(phone)
            try:
                await self.client.sign_in(phone, input("Enter the code you received: "))
            except Exception:
                await self.client.sign_in(password=input("2FA Password Required. Please enter: "))
        
        self.logger.info("✅ Telegram connection successful.")
    
    async def disconnect(self) -> None:
        """
        Gracefully disconnects the Telegram client.
        """
        if self.client and self.client.is_connected():
            self.logger.info("Disconnecting from Telegram...")
            await self.client.disconnect()
    
    async def _synthesize_messages(self, raw_messages: List, channel_alias: str, source_identifier: str) -> List[Dict[str, Any]]:
        """
        A private helper method to handle the advanced album synthesis logic.
        This preserves the exact logic from Mark I that groups related media posts.
        
        Args:
            raw_messages: List of raw Telegram messages
            channel_alias: Channel username for URL generation
            source_identifier: Original source as entered by user
            
        Returns:
            List of synthesized logical posts in unified format
        """
        synthesized_groups = {}
        
        for msg in raw_messages:
            if not msg: 
                continue
                
            group_id = msg.grouped_id or msg.id
            if group_id not in synthesized_groups:
                synthesized_groups[group_id] = {
                    'messages': [], 
                    'text': None, 
                    'main_msg': msg
                }
            
            synthesized_groups[group_id]['messages'].append(msg)
            
            if msg.text:
                synthesized_groups[group_id]['text'] = msg.text
                synthesized_groups[group_id]['main_msg'] = msg
        
        logical_posts = []
        for group_id, group_data in synthesized_groups.items():
            main_msg = group_data['main_msg']
            text = group_data['text']
            
            if text:  # Only process posts with text content
                media_urls = [
                    f'https://t.me/{channel_alias}/{m.id}?single' 
                    for m in group_data['messages'] 
                    if m.media
                ]
                
                # Create unified post using the base connector helper
                unified_post = self._create_unified_post(
                    platform="telegram",
                    source=source_identifier,  # Exactly as user enters
                    url=f'https://t.me/{channel_alias}/{main_msg.id}',
                    content=text,
                    date=main_msg.date,
                    media_urls=media_urls,
                    categories=[],  # Telegram posts don't have built-in categories, but hashtags could be extracted here in future
                    metadata={}  # Empty for Mark II
                )
                
                # Remove all legacy compatibility fields - use ONLY new unified structure
                logical_posts.append(unified_post)
        
        return logical_posts
    
    @expose_tool(
        name="fetch_recent_posts",
        description="Fetch the most recent posts from a Telegram channel with flexible limit options",
        parameters={
            "source_identifier": {
                "type": "str", 
                "description": "Channel username (with or without @)", 
                "required": True
            },
            "limit": {
                "type": "Union[int, str]", 
                "description": "Number of posts (1-1000), negative for message ID start (-123), or '-all' for entire channel", 
                "required": True
            }
        },
        category="telegram",
        examples=[
            "fetch_recent_posts('durov', 10)",
            "fetch_recent_posts('@telegram', 50)",
            "fetch_recent_posts('breaking_news', -456)",
            "fetch_recent_posts('important_channel', '-all')"
        ],
        returns="List of posts in unified format with platform, source, url, content, date, media_urls",
        notes="Use '-all' carefully on large channels. Negative numbers start from specific message ID."
    )
    async def fetch_posts(self, source_identifier: str, limit: Union[int, str]) -> List[Dict[str, Any]]:
        """
        UNIFIED API: Single method for all Telegram fetching needs.
        
        This method handles all fetching scenarios with intelligent limit parsing:
        - Normal integer (e.g., 10): Fetch N recent posts
        - Negative integer (e.g., -123): Fetch starting from message ID 123
        - String "-all": Fetch ALL posts from channel (for database population)
        
        Future database integration will allow date-based filtering without API calls.
        
        Args:
            source_identifier: Telegram channel username (with or without @)
            limit: Flexible limit parameter:
                   - int > 0: Number of recent posts
                   - int < 0: Starting message ID (abs value)
                   - "-all": Fetch entire channel history
            
        Returns:
            List of posts in unified format, empty list on any failure
        """
        # Input validation
        if not source_identifier or not isinstance(source_identifier, str):
            self.logger.error("Invalid source_identifier provided")
            return []
        
        # Parse limit parameter
        try:
            fetch_mode, fetch_value = self._parse_limit_parameter(limit)
        except ValueError as e:
            self.logger.error(f"Invalid limit parameter: {e}")
            return []
        
        # Connection validation
        if not self.client or not self.client.is_connected():
            self.logger.error("Telegram client not connected")
            return []
        
        channel_username = source_identifier.lstrip('@')
        
        # Log the operation
        if fetch_mode == "recent":
            self.logger.info(f"🔍 Fetching {fetch_value} recent posts from @{channel_username}")
        elif fetch_mode == "from_id":
            self.logger.info(f"🔍 Fetching posts from message ID {fetch_value} from @{channel_username}")
        elif fetch_mode == "all":
            self.logger.info(f"🔍 Fetching ALL posts from @{channel_username} (database population mode)")
        
        try:
            # Protected call to internal implementation
            posts = await asyncio.wait_for(
                self._fetch_posts_internal(channel_username, fetch_mode, fetch_value),
                timeout=self._calculate_timeout(fetch_mode)
            )
            
            self.logger.info(f"✅ Successfully fetched {len(posts)} posts from @{channel_username}")
            return posts
            
        except asyncio.TimeoutError:
            timeout = self._calculate_timeout(fetch_mode)
            self.logger.warning(f"⏰ Fetch from @{channel_username} timed out after {timeout}s")
            return []
        except Exception as e:
            self.logger.error(f"❌ Protected fetch failed from @{channel_username}: {str(e)}")
            return []
    
    # =============================================================================
    # INTERNAL IMPLEMENTATION - Pure Defended Logic
    # =============================================================================
    
    async def _fetch_posts_internal(self, channel_username: str, mode: str, limit: int) -> List[Dict[str, Any]]:
        """
        INTERNAL: Pure Telegram post fetching logic without external protections.
        
        This method contains only the core business logic for fetching Telegram posts.
        It assumes valid inputs and connected client. Used by:
        - Public fetch_posts() method (with protection)
        - Future internal methods that need raw access
        - Testing scenarios where you want to test core logic
        
        Args:
            channel_username: Clean channel username (no @ prefix)
            limit: Valid positive integer
            
        Returns:
            List of posts in unified format
            
        Raises:
            Various Telegram API exceptions (handled by caller)
        """
        all_synthesized_posts = []
        processed_ids = set()
        last_message_id = 0
        fetch_chunk_size = 100
        max_fetches = 20
        
        try:
            # Get channel entity with comprehensive error handling
            await self.throttle_if_needed()
            
            try:
                entity = await self.client.get_entity(channel_username)
            except ChannelInvalidError:
                self.logger.error(f"ERROR: Failed to process @{channel_username} - Reason: Channel does not exist or is invalid")
                raise ValueError(f"Channel @{channel_username} does not exist or is invalid")
            except ChannelPrivateError:
                self.logger.error(f"ERROR: Failed to process @{channel_username} - Reason: Channel is private or requires subscription")
                raise ValueError(f"Channel @{channel_username} is private or requires subscription")
            except UsernameInvalidError:
                self.logger.error(f"ERROR: Failed to process @{channel_username} - Reason: Invalid username format")
                raise ValueError(f"Invalid username format: @{channel_username}")
            except UsernameNotOccupiedError:
                self.logger.error(f"ERROR: Failed to process @{channel_username} - Reason: Username not found")
                raise ValueError(f"Username not found: @{channel_username}")
            except (ConnectionError, TimeoutError) as e:
                self.logger.error(f"ERROR: Failed to process @{channel_username} - Reason: Network error: {str(e)}")
                raise ConnectionError(f"Network error accessing @{channel_username}: {str(e)}")
            except FloodWaitError as e:
                self.logger.error(f"ERROR: Failed to process @{channel_username} - Reason: Rate limit exceeded, need to wait {e.seconds} seconds")
                raise ConnectionError(f"Rate limit exceeded for @{channel_username}, need to wait {e.seconds} seconds")
            except RPCError as e:
                self.logger.error(f"ERROR: Failed to process @{channel_username} - Reason: Telegram API error: {str(e)}")
                raise ConnectionError(f"Telegram API error for @{channel_username}: {str(e)}")
            except Exception as e:
                self.logger.error(f"ERROR: Failed to process @{channel_username} - Reason: Unexpected error: {str(e)}")
                raise ConnectionError(f"Unexpected error accessing @{channel_username}: {str(e)}")
            
            # Fetch messages in chunks
            for fetch_attempt in range(max_fetches):
                if len(all_synthesized_posts) >= limit:
                    break

                self.logger.info(f"fetching attempt #{fetch_attempt + 1} for @{channel_username}...")
                    
                try:
                    await self.throttle_if_needed()
                    
                    try:
                        messages = await self.client.get_messages(
                            entity, 
                            limit=min(fetch_chunk_size, limit * 3),  # Fetch extra to account for filtering
                            offset_id=last_message_id
                        )
                    except ChannelPrivateError:
                            self.logger.error(f"ERROR: Failed to fetch from @{channel_username} - Reason: Channel became private during operation")
                            break
                    except FloodWaitError as e:
                        self.logger.warning(f"Rate limit hit for @{channel_username}, waiting {e.seconds} seconds...")
                        await asyncio.sleep(e.seconds)
                        continue
                    except ConnectionError as e:
                        self.logger.error(f"ERROR: Failed to fetch from @{channel_username} - Reason: Connection lost: {str(e)}")
                        break
                    except TimeoutError:
                        self.logger.error(f"ERROR: Failed to fetch from @{channel_username} - Reason: Message fetch timed out")
                        break
                    except RPCError as e:
                        self.logger.error(f"ERROR: Failed to fetch from @{channel_username} - Reason: Telegram API error during fetch: {str(e)}")
                        break
                    except Exception as e:
                        self.logger.error(f"ERROR: Failed to fetch from @{channel_username} - Reason: Unexpected error during message fetch: {str(e)}")
                        break
                    
                    if not messages:
                        self.logger.info(f"No messages found in attempt #{fetch_attempt + 1} for @{channel_username}")
                        break
                    
                    # Synthesize messages with error handling
                    try:
                        synthesized = await self._synthesize_messages(messages, channel_username, f"@{channel_username}")
                        
                        for post in synthesized:
                            try:
                                # Use URL as unique identifier since we removed id field
                                post_url = post.get('url')
                                if post_url and post_url not in processed_ids:
                                    all_synthesized_posts.append(post)
                                    processed_ids.add(post_url)
                            except Exception as e:
                                self.logger.warning(f"Error processing synthesized post: {e}")
                                continue
                        
                        last_message_id = messages[-1].id
                        
                    except Exception as e:
                        self.logger.error(f"Error synthesizing messages from @{channel_username}: {e}")
                        break
                    
                except Exception as e:
                        self.logger.error(f"Error during fetch attempt #{fetch_attempt+1} for @{channel_username}: {e}")
                        # Continue with next attempt unless it's a critical error
                        if fetch_attempt >= max_fetches - 1:
                            break
                        continue
            
            # Sort and return posts with error handling
                try:
                    # Sort by date (newest first), then take the limit, then sort chronologically
                    final_posts = sorted(all_synthesized_posts, key=lambda p: p.get('date', datetime.min.replace(tzinfo=timezone.utc)), reverse=True)[:limit]
                    result = sorted(final_posts, key=lambda p: p.get('date', datetime.min.replace(tzinfo=timezone.utc)))
                    
                    self.logger.info(f"Successfully fetched {len(result)} posts from @{channel_username}")
                    return result
                    
                except Exception as e:
                    self.logger.error(f"Error sorting posts from @{channel_username}: {e}")
                    return all_synthesized_posts[:limit]  # Return unsorted if sorting fails
             
        except Exception as e:
            self.logger.error(f"ERROR: Failed to fetch from @{channel_username} - Reason: Critical error: {str(e)}")
            return []
        

    # =============================================================================
    # HELPER METHODS
    # =============================================================================
    
    def _parse_limit_parameter(self, limit: Union[int, str]) -> tuple[str, int]:
        """
        Parse the flexible limit parameter into fetch mode and value.
        
        Returns:
            Tuple of (fetch_mode, fetch_value) where:
            - ("recent", N): Fetch N recent posts
            - ("from_id", ID): Fetch from message ID
            - ("all", 0): Fetch all posts
        """
        if isinstance(limit, str):
            if limit == "-all":
                self.logger.info(f"Fetching all posts from channel")
                return ("all", 0)
            else:
                self.logger.error(f"Invalid string limit: {limit}. Only '-all' is supported.")
                raise ValueError(f"Invalid string limit: {limit}. Only '-all' is supported.")
        elif isinstance(limit, int):
            if limit > 0:
                self.logger.info(f"Fetching {limit} recent posts from channel")
                return ("recent", limit)
            elif limit < 0:
                self.logger.info(f"Fetching posts from message ID {abs(limit)} from channel")
                return ("from_id", abs(limit))
            else:
                self.logger.error(f"Limit cannot be zero")
                raise ValueError("Limit cannot be zero")
        else:
            self.logger.error(f"Invalid limit type: {type(limit)}. Limit must be int or str.")
            raise ValueError(f"Limit must be int or str, got {type(limit)}")
    
    def _calculate_timeout(self, fetch_mode: str) -> int:
        """Calculate appropriate timeout based on fetch mode."""
        if fetch_mode == "all":
            self.logger.info(f"Calculating timeout for all posts")
            return self.COOLDOWN_SECONDS * 10  # Much longer timeout for full channel fetch
        elif fetch_mode == "from_id":
            self.logger.info(f"Calculating timeout for ID-based fetch")
            return self.COOLDOWN_SECONDS * 3   # Longer timeout for ID-based fetch
        else:
            self.logger.info(f"Calculating timeout for recent posts")
            return self.COOLDOWN_SECONDS * 2   # Normal timeout for recent posts
    