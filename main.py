import streamlit as st
from telethon.sync import TelegramClient, events
import time
import asyncio
import nest_asyncio
from asyncio.exceptions import CancelledError
import threading
import os
from telethon.errors import SessionPasswordNeededError

# Enable nested event loops
nest_asyncio.apply()

def get_credentials():
    try:
        api_id = st.secrets["TELEGRAM_API_ID"]
        api_hash = st.secrets["TELEGRAM_API_HASH"]
    except Exception as e:
        st.error("API credentials not found in secrets!")
        st.stop()
    
    return api_id, api_hash

async def handle_phone_code_request(client, phone):
    """Handle phone code verification through Streamlit UI"""
    if 'code_requested' not in st.session_state:
        st.session_state.code_requested = True
        st.info("Please check your Telegram app for the verification code.")
        
    code = st.text_input("Enter Telegram verification code:", key="verification_code")
    
    if st.button("Submit Code"):
        try:
            await client.sign_in(phone, code)
            st.success("Successfully authenticated!")
            st.session_state.authenticated = True
            return True
        except SessionPasswordNeededError:
            # Handle 2FA if enabled
            password = st.text_input("Two-factor authentication enabled. Please enter your password:", type="password")
            if st.button("Submit Password"):
                try:
                    await client.sign_in(password=password)
                    st.success("Successfully authenticated with 2FA!")
                    st.session_state.authenticated = True
                    return True
                except Exception as e:
                    st.error(f"Error with 2FA: {str(e)}")
                    return False
        except Exception as e:
            st.error(f"Invalid code: {str(e)}")
            return False
    return False

def create_telegram_client(api_id, api_hash, phone_number):
    # Create session name with phone number
    session_file = f'session_{phone_number.replace("+", "")}'
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    client = TelegramClient(session_file, api_id, api_hash, loop=loop)
    return client, loop


# [Previous async functions remain the same: send_message_and_wait_async, click_button_async, 
# check_last_message_async, wait_for_response_async, process_address_async]

async def send_message_and_wait_async(client, bot, message_text, reply_to_last=False, show_response=False, delay=2, wait_for_buttons=False):
    try:
        messages = await client.get_messages(bot, limit=1)

        if reply_to_last and messages:
            await client.send_message(bot, message_text, reply_to=messages[0].id)
            st.info(f"Replied to last bot message: {message_text}")
        else:
            await client.send_message(bot, message_text)
            st.info(f"Sent: {message_text}")

        await asyncio.sleep(delay)

        if wait_for_buttons:
            await wait_for_response_async(client, bot)

        if show_response:
            await check_last_message_async(client, bot)
    except Exception as e:
        st.error(f"Error sending message: {str(e)}")

async def click_button_async(client, bot, button_text, show_buttons=False):
    try:
        messages = await client.get_messages(bot, limit=1)

        if messages and messages[0].buttons:
            if show_buttons:
                st.write("\nAvailable Buttons:")
                for row in messages[0].buttons:
                    for button in row:
                        st.write(f"- {button.text}")

            for row in messages[0].buttons:
                for button in row:
                    if button.text.lower() == button_text.lower():
                        await button.click()
                        st.info(f"Clicked button: {button.text}")
                        await asyncio.sleep(2)
                        return True
        else:
            st.warning("No buttons found.")
        return False
    except Exception as e:
        st.error(f"Error clicking button: {str(e)}")
        return False

async def check_last_message_async(client, bot):
    try:
        messages = await client.get_messages(bot, limit=1)
        
        if messages:
            last_message = messages[0].message.lower()
            #st.write(f"\nBot Reply: {messages[0].message}")

            if "swap failed" in last_message:
                st.error("⚠️ Swap failed: Network congestion detected. Try again later.")
                return False
        return True
    except Exception as e:
        st.error(f"Error checking last message: {str(e)}")
        return False

async def wait_for_response_async(client, bot, timeout=90):
    try:
        start_time = time.time()

        while time.time() - start_time < timeout:
            messages = await client.get_messages(bot, limit=1)
            
            if messages and messages[0].buttons:
                st.info("New buttons detected, proceeding...")
                return

            last_message = messages[0].message.lower()
            if "swap failed" in last_message:
                st.error("⚠️ Swap failed: Network congestion detected. Try again later.")
                return

            st.info("Waiting for a response...")
            await asyncio.sleep(3)

        st.warning("⏳ Timeout reached: No response received. Proceeding with caution.")
    except Exception as e:
        st.error(f"Error waiting for response: {str(e)}")

async def process_address_async(client, bot, data):
    try:
        st.subheader(f"Processing address: {data['address']}")
        
        # Start bot interaction
        await send_message_and_wait_async(client, bot, '/start')
        
        # Buy process
        await click_button_async(client, bot, 'buy')
        await send_message_and_wait_async(client, bot, data['address'])
        await click_button_async(client, bot, 'Buy X SOL')
        await send_message_and_wait_async(client, bot, data['buy_amount'], 
            reply_to_last=True, wait_for_buttons=True)

        # Set limits and triggers if swap successful
        if await check_last_message_async(client, bot):
            await click_button_async(client, bot, 'limit', False)
            
            for limit, trigger in zip(data['limit'], data['trigger']):
                await click_button_async(client, bot, 'Limit Sell X %')
                await send_message_and_wait_async(client, bot, limit, reply_to_last=True)
                await send_message_and_wait_async(client, bot, trigger, reply_to_last=True)
                await click_button_async(client, bot, 'Confirm', False)
                st.success(f"Trigger {trigger} with Stop_loss {limit} set successfully")
            st.success(f"All triggers and stoploss for {data["address"]} successfully added ")
            await click_button_async(client, bot, 'Close', False)
            await asyncio.sleep(5)
    except Exception as e:
        st.error(f"Error processing address: {str(e)}")

def main():
    st.set_page_config(layout="wide", page_title="Telegram Bot Controller")
    st.title("Telegram Bot Controller")

    # Initialize session state
    if 'authenticated' not in st.session_state:
        st.session_state.authenticated = False
    if 'phone_number' not in st.session_state:
        st.session_state.phone_number = ""
    if 'bot_username' not in st.session_state:
        st.session_state.bot_username = ""

    # Get credentials
    api_id, api_hash = get_credentials()

    # Display credential status
    st.sidebar.success("API Credentials loaded successfully")

    # Connection details in sidebar
    with st.sidebar:
        st.header("Connection Details")
        phone_number = st.text_input(
            "Phone Number", 
            placeholder="+44754655515 (With country code)",
            value=st.session_state.phone_number,
            key="phone_input"
        )

        # Predefined bot list with option for custom input
        default_bots = [
            "Select a bot or enter custom",
            "monza_bonkbot",
            "sonic_bonkbot",
            "bonkbot_bot",
            "Custom"
        ]
        
        bot_selection = st.selectbox(
            "Select Bot", 
            options=default_bots,
            key="bot_selection"
        )
        
        if bot_selection == "Custom":
            bot_username = st.text_input(
                "Enter Custom Bot Username",
                key="custom_bot"
            )
        else:
            bot_username = bot_selection if bot_selection != "Select a bot or enter custom" else ""

        # Authentication button
        if st.button("Authenticate", key="auth_button"):
            if not phone_number:
                st.error("Please enter a phone number!")
                return
            if not bot_username:
                st.error("Please select or enter a bot username!")
                return
            
            st.session_state.phone_number = phone_number
            st.session_state.bot_username = bot_username
            st.session_state.start_auth = True

    # Handle authentication
    if 'start_auth' in st.session_state and st.session_state.start_auth and not st.session_state.authenticated:
        try:
            client, loop = create_telegram_client(api_id, api_hash, st.session_state.phone_number)
            
            async def authenticate():
                try:
                    await client.connect()
                    if not await client.is_user_authorized():
                        await client.send_code_request(st.session_state.phone_number)
                        if await handle_phone_code_request(client, st.session_state.phone_number):
                            st.rerun()
                    else:
                        st.session_state.authenticated = True
                        st.rerun()
                except Exception as e:
                    st.error(f"Authentication error: {str(e)}")
                finally:
                    await client.disconnect()

            loop.run_until_complete(authenticate())
            
        except Exception as e:
            st.error(f"Connection error: {str(e)}")
        return



    # Main interface (only shown after authentication)
    if st.session_state.authenticated:
        st.success(f"Authenticated with phone: {st.session_state.phone_number}")
        st.success(f"Connected to bot: {st.session_state.bot_username}")
        
        # Add logout button
        if st.sidebar.button("Logout"):
            # Clear session state
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            # Delete session file
            session_file = f'session_{st.session_state.phone_number.replace("+", "")}.session'
            if os.path.exists(session_file):
                os.remove(session_file)
            st.rerun()
        num_addresses = st.number_input("Number of Addresses", min_value=1, value=1)
        
        address_data = []
        
        for i in range(int(num_addresses)):
            st.subheader(f"Address {i+1} Configuration")
            col1, col2 = st.columns(2)
            
            with col1:
                token_address = st.text_input(
                    f"Token Address {i+1}", 
                    placeholder="JECt5SVpSCdWpq6et5egLJwso"
                )
                buy_amount = st.text_input(
                    f"Buy Amount {i+1}", 
                    placeholder="0.000001"
                )
            
            with col2:
                num_triggers = st.number_input(
                    f"Number of Triggers for Address {i+1}", 
                    min_value=1, 
                    value=1
                )
                limits = []
                triggers = []
                
                for j in range(int(num_triggers)):
                    col3, col4 = st.columns(2)
                    with col3:
                        limit = st.text_input(f"Limit {j+1} for Address {i+1}")
                    with col4:
                        trigger = st.text_input(f"Trigger {j+1} for Address {i+1}")
                    if limit and trigger:
                        limits.append(limit)
                        triggers.append(trigger)
            
            if token_address and buy_amount:
                address_data.append({
                    "address": token_address,
                    "buy_amount": buy_amount,
                    "limit": limits,
                    "trigger": triggers
                })

        if st.button("Start Process"):
            if not phone_number or not bot_username:
                st.error("Please enter phone number and bot username!")
                return
                
            if not address_data:
                st.error("Please enter at least one address configuration!")
                return

            try:
                with st.spinner("Connecting to Telegram..."):
                    client, loop = create_telegram_client(api_id, api_hash, phone_number)
                    
                    async def run_client():
                        try:
                            await client.start(phone_number)
                            st.success("Connected to Telegram successfully!")

                            bot = await client.get_entity(bot_username)

                            for data in address_data:
                                await process_address_async(client, bot, data)
                        finally:
                            await client.disconnect()

                    try:
                        loop.run_until_complete(run_client())
                    finally:
                        loop.stop()
                        loop.close()
                        
            except Exception as e:
                st.error(f"An error occurred: {str(e)}")

if __name__ == "__main__":
    main()