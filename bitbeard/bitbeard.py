import discord
from discord.ext import commands
import qbittorrentapi
import subprocess
import asyncio
import os
import logging
from datetime import datetime
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn
import requests
from fastapi.middleware.cors import CORSMiddleware
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
from xml.etree import ElementTree
import time
import math
from discord.ui import View, Select, Button

# Set up logging
logging.basicConfig(filename='bitbeard.log', level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# Read configuration from environment variables
def get_env_var(name, required=True, default=None, cast=None):
    value = os.environ.get(name, default)
    if required and value is None:
        logging.error(f"Required environment variable '{name}' not set.")
        raise RuntimeError(f"Required environment variable '{name}' not set.")
    if cast and value is not None:
        try:
            value = cast(value)
        except Exception as e:
            logging.error(f"Failed to cast environment variable '{name}': {e}")
            raise
    return value

# Qbittorrent client setup (host and port are always localhost:8080)
try:
    qbt_client = qbittorrentapi.Client(
        host="localhost",
        port=8080,
        username=get_env_var('QBITTORRENT_USERNAME'),
        password=get_env_var('QBITTORRENT_PASSWORD')
    )
except Exception as e:
    logging.error(f"Error setting up QBittorrent client: {e}")
    raise

try:
    qbt_client.auth_log_in()
except qbittorrentapi.LoginFailed as e:
    logging.error(f"Login to qBittorrent failed: {e}")
    print(f"Login to qBittorrent failed: {e}")

# Discord bot setup
intents = discord.Intents.default()
intents.messages = True
intents.reactions = True
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# FastAPI setup
app = FastAPI()

# Enable CORS for all origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # You can restrict this to specific origins if needed
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class TorrentRequest(BaseModel):
    magnet_link: str
    category: str

class SearchRequest(BaseModel):
    query: str

@app.post("/download")
async def api_download(request: TorrentRequest):
    try:
        await add_and_monitor_download(request.magnet_link, None, request.category)
        return {"message": "Download started successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/search")
async def api_search(request: SearchRequest):
    results = search_for_magnet_links(request.query)
    return {"results": results}

@app.get("/progress")
async def api_progress():
    torrents = qbt_client.torrents_info(status_filter='downloading')
    progress = []
    for torrent in torrents:
        eta_hours, eta_remainder = divmod(torrent.eta, 3600)
        eta_minutes, eta_seconds = divmod(eta_remainder, 60)
        eta_formatted = f"{eta_hours}h:{eta_minutes}m:{eta_seconds}s"
        progress.append({
            "name": torrent.name,
            "progress": f"{torrent.progress * 100:.2f}%",
            "eta": eta_formatted
        })
    return {"progress": progress}

@app.post("/cancel")
async def api_cancel():
    torrents = qbt_client.torrents_info()
    for torrent in torrents:
        qbt_client.torrents_delete(torrent_hashes=torrent.hash)
    return {"message": "All torrents have been cancelled"}

@bot.event
async def on_ready():
    logging.info(f'{bot.user.name} has connected to Discord!')
    print(f'{bot.user.name} has connected to Discord!')

async def add_and_monitor_download(magnet_link, message, category):
    base_download_dir = get_env_var('BASE_DOWNLOAD_DIR')
    download_dir = os.path.join(base_download_dir, category)
    
    try:
        qbt_client.torrents_add(urls=magnet_link, save_path=download_dir)
        log_message = f"Magnet link added to qBittorrent under {category}."
        logging.info(log_message)
        if message:
            await message.channel.send(log_message)
        print(log_message)
    except Exception as e:
        error_message = f"Failed to add magnet link to qBittorrent: {e}"
        logging.error(error_message)
        if message:
            await message.channel.send("Failed to add magnet link to qBittorrent.")
        print(error_message)
        return
    
    while True:
        active_torrents = qbt_client.torrents_info(status_filter='downloading')
        completed_torrents = qbt_client.torrents_info(status_filter='completed')
        
        for torrent in completed_torrents:
            qbt_client.torrents_delete(torrent_hashes=torrent.hash)
            announce_channel = bot.get_channel(int(get_env_var('DISCORD_ANNOUNCE_CHANNEL_ID')))
            completion_message = f"{torrent.name} has been added to Bitbeard under {category}."
            logging.info(completion_message)
            await announce_channel.send(completion_message)
            if message:
                await message.channel.send(f"Completed and removed torrent: {torrent.name}")
            
        
        if not active_torrents:
            completion_message = "All downloads completed."
            logging.info(completion_message)
            if message:
                await message.channel.send(completion_message)
            print(completion_message)
            break
        
        await asyncio.sleep(15)

def search_for_magnet_links(search_query):
    jackett_api_key = get_env_var('JACKETT_API_KEY')
    
    response = requests.get(f"http://127.0.0.1:9117/api/v2.0/indexers/all/results/torznab/api?apikey={jackett_api_key}&t=search&cat=&q={search_query}")
    
    if response.status_code != 200:
        logging.error(f"Jackett search failed: {response.status_code}")
        return []
    
    root = ElementTree.fromstring(response.content)
    results = root.findall('channel/item')
    formatted_results = []
    
    for result in results:
        namespaces = {'ns0': 'http://torznab.com/schemas/2015/feed'}
        seeders_element = result.find('.//ns0:attr[@name="seeders"]', namespaces)
        seeders = int(seeders_element.attrib['value']) if seeders_element is not None else 0
        size_element = result.find('size')
        size_gb = int(size_element.text) / (1024 ** 3) if size_element is not None else 0
        
        formatted_results.append({
            "title": result.find('title').text,
            "magnet_link": result.find('link').text,
            "seeders": seeders,
            "size_gb": size_gb
        })
    
    return formatted_results

class SearchResultsView(View):
    def __init__(self, results, page=0):
        super().__init__(timeout=300)
        self.results = results
        self.page = page
        self.update_buttons()

    def update_buttons(self):
        self.clear_items()
        start_idx = self.page * 5
        page_results = self.results[start_idx:start_idx + 5]
        
        for i, result in enumerate(page_results):
            select_button = Button(label=f"{i+1}", style=discord.ButtonStyle.primary, custom_id=f"select_{i}")
            select_button.callback = self.select_callback
            self.add_item(select_button)
            
        if self.page > 0:
            prev_button = Button(label="Previous", style=discord.ButtonStyle.secondary, custom_id="prev")
            prev_button.callback = self.prev_callback
            self.add_item(prev_button)
            
        if (self.page + 1) * 5 < len(self.results):
            next_button = Button(label="Next", style=discord.ButtonStyle.secondary, custom_id="next")
            next_button.callback = self.next_callback
            self.add_item(next_button)
            
        cancel_button = Button(label="Cancel", style=discord.ButtonStyle.danger, custom_id="cancel")
        cancel_button.callback = self.cancel_callback
        self.add_item(cancel_button)

    async def select_callback(self, interaction):
        try:
            # First acknowledge the interaction
            await interaction.response.defer(ephemeral=True)
            
            # Get the index from the button's custom_id
            idx = int(interaction.data['custom_id'].split("_")[1])
            selected_result = self.results[self.page * 5 + idx]
            
            # Create the category selection view
            category_view = View(timeout=300)
            category_select = Select(
                placeholder="Choose a category",
                options=[
                    discord.SelectOption(label="Movie", emoji="🎬"),
                    discord.SelectOption(label="TV Show", emoji="📺"),
                    discord.SelectOption(label="Other", emoji="📁")
                ]
            )
            
            async def category_callback(category_interaction):
                try:
                    # First acknowledge the category selection
                    await category_interaction.response.defer()
                    
                    # Start the download
                    await add_and_monitor_download(selected_result['magnet_link'], interaction, category_select.values[0])
                    
                    # Delete the category selection message
                    await category_interaction.message.delete()
                    
                except Exception as e:
                    if not category_interaction.response.is_done():
                        await category_interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
                    else:
                        await category_interaction.followup.send(f"Error: {str(e)}", ephemeral=True)
            
            category_select.callback = category_callback
            category_view.add_item(category_select)
            
            # Send the category selection as a followup
            await interaction.followup.send("Select a category:", view=category_view, ephemeral=True)
            
        except Exception as e:
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(f"An error occurred: {str(e)}", ephemeral=True)
                else:
                    await interaction.followup.send(f"An error occurred: {str(e)}", ephemeral=True)
            except:
                logging.error(f"Failed to handle select callback: {str(e)}")

    async def prev_callback(self, interaction):
        self.page -= 1
        await self.update_message(interaction)

    async def next_callback(self, interaction):
        self.page += 1
        await self.update_message(interaction)

    async def cancel_callback(self, interaction):
        await interaction.message.delete()

    async def update_message(self, interaction):
        self.update_buttons()
        content = self.format_results()
        await interaction.response.edit_message(content=content, view=self)

    def format_results(self):
        start_idx = self.page * 5
        page_results = self.results[start_idx:start_idx + 5]
        total_pages = math.ceil(len(self.results) / 5)

        table = "```\n"
        table += f"{'#':<3} {'Title':<50} {'Size':<10} {'Seeders':<8}\n"
        table += "-" * 71 + "\n"
        
        for i, result in enumerate(page_results, 1):
            title = result['title'][:47] + "..." if len(result['title']) > 50 else result['title']
            table += f"{i:<3} {title:<50} {result['size_gb']:.2f}GB {result['seeders']:<8}\n"
        
        table += f"\nPage {self.page + 1}/{total_pages}"
        table += "```"
        return table

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    content = message.content.lower()
    logging.info(f"Received message: {content}")

    if content == 'fuck, panic!!!':
        panic_message = 'this command has been removed due to how stupid it was. ask snow to reset server for you.'
        logging.warning(panic_message)
        await message.channel.send(panic_message)
        return

    if content.startswith('magnet:?'):
        category_select = Select(
            placeholder="Choose a category",
            options=[
                discord.SelectOption(label="Movie", emoji="🎬"),
                discord.SelectOption(label="TV Show", emoji="📺"),
                discord.SelectOption(label="Other", emoji="📁")
            ]
        )
        
        async def category_callback(interaction):
            try:
                # First acknowledge the category selection
                await interaction.response.defer()
                
                # Start the download
                await add_and_monitor_download(content, message, category_select.values[0])
                
                # Delete the category selection message
                await interaction.message.delete()
                
            except Exception as e:
                if not interaction.response.is_done():
                    await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
                else:
                    await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)
            
        category_select.callback = category_callback
        view = View(timeout=300)
        view.add_item(category_select)
        
        await message.channel.send("Select a category:", view=view)
        return

    if content == 'fix perms':
        await message.channel.send('this command is now deprecated and there is no reason to use it. if somethin weird is goin on let snow know')
        return
        
    if content == 'cancel':
        await handle_cancel(message)
    elif content == 'progress':
        await handle_progress(message)
    elif content not in ['yes', 'no', 'next', 'movie', 'tv show', 'other']:
        await message.channel.send(f"Querying trackers for '{content}'. By the way, you look lovely today. Arrr.")
        search_results = search_for_magnet_links(content)
        if not search_results:
            await message.channel.send(f"No results found for '{content}'")
            return
            
        view = SearchResultsView(search_results)
        await message.channel.send(view.format_results(), view=view)

async def handle_cancel(message):
    torrents = qbt_client.torrents_info()
    if not torrents:
        await message.channel.send("No active torrents to cancel.")
        return

    confirm_view = View(timeout=300)
    confirm_button = Button(label="Confirm", style=discord.ButtonStyle.danger)
    cancel_button = Button(label="Abort", style=discord.ButtonStyle.secondary)

    async def confirm_callback(interaction):
        for torrent in torrents:
            qbt_client.torrents_delete(torrent_hashes=torrent.hash)
        await interaction.response.edit_message(content="All torrents have been cancelled.", view=None)

    async def cancel_callback(interaction):
        await interaction.response.edit_message(content="Cancellation aborted.", view=None)

    confirm_button.callback = confirm_callback
    cancel_button.callback = cancel_callback
    confirm_view.add_item(confirm_button)
    confirm_view.add_item(cancel_button)

    await message.channel.send("Are you sure you want to cancel all downloads?", view=confirm_view)

async def handle_progress(message):
    torrents = qbt_client.torrents_info(status_filter='downloading')
    if not torrents:
        await message.channel.send("No active downloads.")
        return

    progress_table = "```\n"
    progress_table += f"{'Name':<40} {'Progress':<10} {'ETA':<15}\n"
    progress_table += "-" * 65 + "\n"
    
    for torrent in torrents:
        eta_hours, eta_remainder = divmod(torrent.eta, 3600)
        eta_minutes, eta_seconds = divmod(eta_remainder, 60)
        eta_formatted = f"{eta_hours}h:{eta_minutes}m:{eta_seconds}s"
        name = torrent.name[:37] + "..." if len(torrent.name) > 40 else torrent.name
        progress_table += f"{name:<40} {torrent.progress * 100:>8.2f}% {eta_formatted:<15}\n"
    
    progress_table += "```"
    await message.channel.send(progress_table)

# Read Discord bot token from environment variable
bot_token = get_env_var('DISCORD_BOT_TOKEN')

# Run both the Discord bot and FastAPI server
async def main():    
    # Start FastAPI server
    config = uvicorn.Config(app, host="0.0.0.0", port=9870)
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    
    # Start Discord bot
    await bot.start(bot_token)
    
    # Wait for both tasks
    await server_task

if __name__ == "__main__":
    asyncio.run(main())
