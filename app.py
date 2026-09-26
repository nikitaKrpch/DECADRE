from flask import Flask, render_template, request, jsonify, send_file, flash, redirect, url_for, make_response, session
from functools import wraps
import os
import pandas as pd
import asyncio
import threading
import time
import uuid
from werkzeug.utils import secure_filename
import json
from datetime import datetime, timedelta
import yaml
from dotenv import load_dotenv

import logging
import os
from logging.handlers import RotatingFileHandler
from datetime import datetime

load_dotenv()  # Load environment variables from .env

def setup_logging(app):
    """Setup unified logging configuration for the Flask app"""
    
    # Create logs directory if it doesn't exist
    if not os.path.exists('logs'):
        os.makedirs('logs')
    
    # Create a unified log file with rotation
    file_handler = RotatingFileHandler(
        'logs/app.log', 
        maxBytes=20971520,  # 20MB
        backupCount=10
    )
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s [%(pathname)s:%(lineno)d]'
    ))
    file_handler.setLevel(logging.INFO)
    
    # Set up the main app logger
    app.logger.addHandler(file_handler)
    app.logger.setLevel(logging.INFO)
    
    # Create a processing logger that uses the same file
    processing_logger = logging.getLogger('processing')
    processing_logger.addHandler(file_handler)
    processing_logger.setLevel(logging.INFO)
    processing_logger.propagate = False  # Prevent duplicate logs
    
    # Also log to console in development
    if app.debug:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG)
        console_handler.setFormatter(logging.Formatter(
            '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
        ))
        app.logger.addHandler(console_handler)
        processing_logger.addHandler(console_handler)
    
    return processing_logger

app = Flask(__name__)
#app.secret_key = 'your-secret-key-change-this-in-production'
app.secret_key = os.getenv("FLASK_SECRET_KEY", "fallback-insecure-key")

# Login configuration
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=8)
ACCESS_PASSWORD = os.getenv("ACCESS_PASSWORD")

# Login required decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('authenticated'):
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

# Setup logging and get the processing logger
processing_logger = setup_logging(app)

@app.after_request
def after_request(response):
    # Minimal CSP - just what you need
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "connect-src 'self';"
    )
    return response

try:
    from gem_asynchronous import (
        load_yaml_config, load_csv, load_corpora, process_articles,
        classify_categories_with_chatGPT, process_article, set_logger
    )
    PROCESSING_AVAILABLE = True
    app.logger.info("✅ gem_asynchronous module loaded successfully")
    set_logger(processing_logger)

except ImportError:
    print("⚠️  gem_asynchronous.py not found. Processing will be simulated.")
    error_msg = "⚠️ gem_asynchronous.py not found. Processing will be simulated."
    app.logger.error(error_msg)
    PROCESSING_AVAILABLE = False



# Configuration
UPLOAD_FOLDER = 'uploads'
OUTPUT_FOLDER = 'outputs'
ALLOWED_EXTENSIONS = {'csv'}

# Ensure directories exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['OUTPUT_FOLDER'] = OUTPUT_FOLDER

# Global variables to track batch processing
processing_jobs = {}
# Dictionary to store cancellation events for each job
job_cancellation_events = {}

def load_config():
    """Load configuration from config/configs.yml"""
    try:
        with open('config/configs.yml', 'r', encoding='utf-8') as file:
            #app.logger.info("📋 Configuration loaded successfully")
            #return yaml.safe_load(file)
        
            config = yaml.safe_load(file)
            # Inject API key from environment
            config['api_key'] = os.getenv("OPENAI_API_KEY", "missing-api-key")

            app.logger.info("🔑 OpenAI API key injected from environment")
            return config

    except Exception as e:
        print(f"Error loading config: {e}")
        error_msg = f"❌ Error loading config: {e}"
        app.logger.error(error_msg)
        return {
            'prompt': 'Configuration file not found. Please check config/configs.yml',
            'model': 'gpt-4',
            'max_tokens': 1500,
            'temperature': 0.3,
            'top_p': 0.7,
            'frequency_penalty': 0.5,
            'presence_penalty': 0.0,
            'api_key': os.getenv("OPENAI_API_KEY", "missing-api-key")
        }

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def generate_output_filename(input_filename):
    """Generate output filename with timestamp"""
    name, ext = os.path.splitext(input_filename)
    #timestamp = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
    return f"output_{name}.csv"

def process_batch_async(job_id):
    """Process batch file asynchronously"""
    job = processing_jobs[job_id]

     # Create cancellation event for this job
    cancellation_event = asyncio.Event()
    job_cancellation_events[job_id] = cancellation_event
    
    try:
        job['status'] = 'processing'
        job['progress'] = 0
        
        input_file = job['input_file']
        config = job['config']
        
        # Generate output filename
        input_filename = os.path.basename(input_file)
        output_filename = generate_output_filename(input_filename)
        output_path = os.path.join(OUTPUT_FOLDER, output_filename)
        
        print(f"🔄 Starting batch processing for job {job_id}")
        print(f"📁 Input: {input_file}")
        print(f"📁 Output: {output_path}")
        processing_logger.info(f"🔄 Starting batch processing for job {job_id}")
        processing_logger.info(f"📁 Input: {input_file}")
        processing_logger.info(f"📁 Output: {output_path}")
        
        if PROCESSING_AVAILABLE:
            # Use your actual processing logic
            try:
                # Load data and corpora using your existing functions
                df = load_csv(input_file)
                if df is None:
                    raise Exception("Failed to load CSV file")
                
                job['total_articles'] = len(df)
                print(f"📊 Total articles to process: {len(df)}")
                processing_logger.info(f"📊 Total articles to process: {len(df)}")

                
                # Update config with output path
                config['csv_file_output'] = output_path
                config['csv_file_input'] = input_file
                
                # Load corpora
                corpora = load_corpora(config.get("dictionaries_files", []))
                
                # Use dict to allow modification in nested function
                finished_count = {'count': 0} 

                # Create progress callback function
                def progress_callback(index, status):
                    # Check if job was cancelled
                    if processing_jobs[job_id]['status'] == 'cancelled':
                        print(f"🛑 Job {job_id} was cancelled during processing")
                        processing_logger.warning(f"🛑 Job {job_id} was cancelled during processing")
                        return False  # Signal to stop processing

                    # Count articles that are FINISHED (either completed OR skipped)
                    if status in ["completed", "skipped", "error"]:
                        finished_count['count'] += 1  # Increment actual count
                        processing_jobs[job_id]['processed_articles'] = finished_count['count']
                        processing_jobs[job_id]['progress'] = int(finished_count['count'] / processing_jobs[job_id]['total_articles'] * 100)
                        print(f"📈 Progress: {processing_jobs[job_id]['progress']}% ({finished_count['count']}/{processing_jobs[job_id]['total_articles']}) - {status}")
                        processing_logger.info(f"📈 Progress: {processing_jobs[job_id]['progress']}% ({finished_count['count']}/{processing_jobs[job_id]['total_articles']}) - {status}")
                        #processing_jobs[job_id]['processed_articles'] = index + 1
                        #processing_jobs[job_id]['progress'] = int((index + 1) / processing_jobs[job_id]['total_articles'] * 100)
                        #print(f"📈 Progress: {processing_jobs[job_id]['progress']}% ({index+1}/{processing_jobs[job_id]['total_articles']}) - {status}")
                        #processing_logger.info(f"📈 Progress: {processing_jobs[job_id]['progress']}% ({index+1}/{processing_jobs[job_id]['total_articles']}) - {status}")
                    elif status == "processing":
                        # For processing status, don't increment the counter, just log
                        print(f"🔄 Processing article {index+1}/{processing_jobs[job_id]['total_articles']}")
                        processing_logger.info(f"🔄 Processing article {index+1}/{processing_jobs[job_id]['total_articles']}")

                    return True  # Continue processing

                # Process articles using your existing async function
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

                # Pass the cancellation event to the processing function
                result = loop.run_until_complete(
                    process_articles(df, corpora, config, progress_callback, cancellation_event)
                )
                loop.close()
                
                # Check if processing was cancelled
                if processing_jobs[job_id]['status'] == 'cancelled':
                    print(f"🛑 Processing cancelled for job {job_id}")
                    processing_logger.warning(f"🛑 Processing cancelled for job {job_id}")
                    return
                
                #job['processed_articles'] = len(df)
                job['status'] = 'completed'
                job['progress'] = 100
                job['output_file'] = output_path

                total_articles = len(df)
                actually_processed = job.get('processed_articles', 0)
                skipped_articles = total_articles - actually_processed

                print(f"✅ Batch processing completed for job {job_id}")
                print(f"📊 Summary: {actually_processed}/{total_articles} articles processed")
                print(f"⚠️  {skipped_articles} articles skipped (token limit exceeded)")

                processing_logger.info(f"✅ Batch processing completed for job {job_id}")
                processing_logger.info(f"📊 Summary: {actually_processed}/{total_articles} articles processed")
                processing_logger.warning(f"⚠️ {skipped_articles} articles skipped (token limit exceeded)")
                
                
            except Exception as e:
                if processing_jobs[job_id]['status'] == 'cancelled':
                    print(f"🛑 Processing cancelled for job {job_id}")
                    processing_logger.warning(f"🛑 Processing cancelled for job {job_id}")
                    return
                print(f"❌ Error in batch processing: {str(e)}")
                error_msg = f"❌ Error in batch processing: {str(e)}"
                processing_logger.error(error_msg)
                job['status'] = 'failed'
                job['error'] = str(e)
                return
                
        else:
            # Simulate processing for testing
            print("🔄 Simulating batch processing...")
            processing_logger.info("🔄 Simulating batch processing...")
            
            # Load CSV to get article count
            try:
                df = pd.read_csv(input_file, encoding='utf-8-sig')
                job['total_articles'] = len(df)
            except Exception as e:
                job['total_articles'] = 10  # Default for simulation
            
            # Simulate processing with progress updates
            for i in range(job['total_articles']):
                if job['status'] == 'cancelled' or cancellation_event.is_set():
                    print(f"🛑 Simulation cancelled for job {job_id}")
                    processing_logger.warning(f"🛑 Simulation cancelled for job {job_id}")
                    return
                
                time.sleep(2)  # Simulate processing time
                job['processed_articles'] = i + 1
                job['progress'] = int((i + 1) / job['total_articles'] * 100)
                print(f"📈 Progress: {job['progress']}% ({i+1}/{job['total_articles']})")
                processing_logger.info(f"📈 Progress: {job['progress']}% ({i+1}/{job['total_articles']})")
            
            # Create a dummy output file for testing
            df_output = df.copy() if 'df' in locals() else pd.DataFrame({'test': ['simulation complete']})
            df_output.to_csv(output_path, index=False, encoding='utf-8-sig')
            
            job['status'] = 'completed'
            job['progress'] = 100
            job['output_file'] = output_path
            
        job['end_time'] = datetime.now()
        duration = (job['end_time'] - job['start_time']).total_seconds()
        print(f"⏱️  Processing completed in {duration:.2f} seconds")
        processing_logger.info(f"⏱️ Processing completed in {duration:.2f} seconds")
        
    except Exception as e:
        if processing_jobs[job_id]['status'] == 'cancelled':
            print(f"🛑 Processing cancelled for job {job_id}")
            processing_logger.warning(f"🛑 Processing cancelled for job {job_id}")
            return
        print(f"❌ Fatal error in batch processing: {str(e)}")
        error_msg = f"❌ Fatal error in batch processing: {str(e)}"
        processing_logger.error(error_msg)
        job['status'] = 'failed'
        job['error'] = str(e)
        job['end_time'] = datetime.now()
    finally:
        # Clean up cancellation event
        if job_id in job_cancellation_events:
            del job_cancellation_events[job_id]

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        password = request.form.get('password')
        if password == ACCESS_PASSWORD:
            session['authenticated'] = True
            session.permanent = True
            app.logger.info(f"✅ User logged in successfully")
            next_page = request.args.get('next')
            return redirect(next_page or url_for('index'))
        else:
            flash('Mot de passe incorrect', 'error')
            app.logger.warning(f"⚠️ Failed login attempt")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('authenticated', None)
    app.logger.info(f"👋 User logged out")
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    return render_template('index.html')

@app.route('/single')
@login_required
def single_article():
    try:
    # Load config and pass to template
        config = load_config()
        # Get default values from config
        default_prompt = config.get('prompt', '')
        default_model = config.get('model', 'gpt-5')
        default_max_tokens = config.get('max_tokens', 1500)
        default_temperature = config.get('temperature', 0.3)
        default_top_p = config.get('top_p', 0.7)
        default_frequency_penalty = config.get('frequency_penalty', 0.5)
        default_presence_penalty = config.get('presence_penalty', 0.0)
        default_max_completion_tokens = config.get('max_completion_tokens', 6000)
        default_reasoning_effort = config.get('reasoning_effort', 'medium')
        default_verbosity = config.get('verbosity', 'medium')
        
    except FileNotFoundError:
        # Fallback if config file is not found
        default_prompt = "Please analyze the following article..."
        default_model = 'gpt-5'
        default_max_tokens = 1500
        default_temperature = 0.3
        default_top_p = 0.7
        default_frequency_penalty = 0.5
        default_presence_penalty = 0.0
        default_max_completion_tokens = 6000
        default_reasoning_effort = 'medium'
        default_verbosity = 'medium'
    except Exception as e:
        print(f"Error loading config: {e}")
        app.logger.error(f"❌ Error loading config: {e}")
        # Use fallback values
        default_prompt = "Please analyze the following article..."
        default_model = 'gpt-5'
        default_max_tokens = 1500
        default_temperature = 0.7
        default_top_p = 1.0
        default_frequency_penalty = 0.0
        default_presence_penalty = 0.0
        default_max_completion_tokens = 6000
        default_reasoning_effort = 'medium'
        default_verbosity = 'medium'
    
    return render_template('single_article.html', 
                         default_prompt=default_prompt,
                         default_model=default_model,
                         default_max_tokens=default_max_tokens,
                         default_temperature=default_temperature,
                         default_top_p=default_top_p,
                         default_frequency_penalty=default_frequency_penalty,
                         default_presence_penalty=default_presence_penalty,
                         default_max_completion_tokens=default_max_completion_tokens,
                         default_reasoning_effort=default_reasoning_effort,
                         default_verbosity=default_verbosity
                         )


@app.route('/batch')
@login_required
def batch_processing():
    try:
    # Load config and pass to template
        config = load_config()
        # Get default values from config
        default_prompt = config.get('prompt', '')
        default_model = config.get('model', 'gpt-5')
        default_max_tokens = config.get('max_tokens', 1500)
        default_temperature = config.get('temperature', 0.3)
        default_top_p = config.get('top_p', 0.7)
        default_frequency_penalty = config.get('frequency_penalty', 0.5)
        default_presence_penalty = config.get('presence_penalty', 0.0)
        default_max_completion_tokens = config.get('max_completion_tokens', 6000)
        default_reasoning_effort = config.get('reasoning_effort', 'medium')
        default_verbosity = config.get('verbosity', 'medium')
        
    except FileNotFoundError:
        # Fallback if config file is not found
        app.logger.warning("⚠️ Config file not found, using defaults")
        default_prompt = "Please analyze the following article..."
        default_model = 'gpt-4'
        default_max_tokens = 1500
        default_temperature = 0.3
        default_top_p = 0.7
        default_frequency_penalty = 0.5
        default_presence_penalty = 0.0
        default_max_completion_tokens = 6000
        default_reasoning_effort = 'medium'
        default_verbosity = 'medium'
    except Exception as e:
        print(f"Error loading config: {e}")
        app.logger.error(f"❌ Error loading config: {e}")
        # Use fallback values
        default_prompt = "Please analyze the following article..."
        default_model = 'gpt-4'
        default_max_tokens = 1500
        default_temperature = 0.7
        default_top_p = 1.0
        default_frequency_penalty = 0.0
        default_presence_penalty = 0.0
        default_max_completion_tokens = 6000
        default_reasoning_effort = 'medium'
        default_verbosity = 'medium'
    
    return render_template('batch_processing.html', 
                         default_prompt=default_prompt,
                         default_model=default_model,
                         default_max_tokens=default_max_tokens,
                         default_temperature=default_temperature,
                         default_top_p=default_top_p,
                         default_frequency_penalty=default_frequency_penalty,
                         default_presence_penalty=default_presence_penalty,
                         default_max_completion_tokens=default_max_completion_tokens,
                         default_reasoning_effort=default_reasoning_effort,
                         default_verbosity=default_verbosity
                         )

@app.route('/test')
def test_route():
    """Test route to verify Flask is working"""
    return {
        'status': 'success',
        'message': 'Flask app is running!',
        'python_version': os.sys.version,
        'directories': {
            'uploads': os.path.exists(UPLOAD_FOLDER),
            'outputs': os.path.exists(OUTPUT_FOLDER),
            'templates': os.path.exists('templates'),
            'config': os.path.exists('config')
        }
    }

async def process_single_article_async(article_data, config):
    """Process a single article using the same logic as batch processing"""
    try:
        # Set OpenAI API key
        api_key = config.get('api_key')
        if not api_key:
            raise Exception("❌ No OpenAI API key found in config")
        
        from gem_asynchronous import set_openai_api_key, load_corpora, process_article
        set_openai_api_key(api_key)
        
        # Load corpora
        corpora = load_corpora(config.get("dictionaries_files", []))
        
        # Create a DataFrame-like row structure for compatibility
        row = {
            'article_title': article_data.get('title', ''),
            'article_desc': article_data.get('description', ''),
            'article_content': article_data.get('content', '')
        }
        
        # Create semaphore for single article (not really needed but keeps compatibility)
        semaphore = asyncio.Semaphore(1)
        big_article = {'count': 0}
        
        # Process the single article
        result = await process_article(
            index=0, 
            row=row, 
            corpora=corpora, 
            config=config, 
            big_article=big_article, 
            semaphore=semaphore,
            progress_callback=None,  # No progress callback needed for single article
            cancellation_event=None  # No cancellation for single article
        )
        
        return result
        
    except Exception as e:
        print(f"❌ Error in single article processing: {str(e)}")
        error_msg = f"❌ Error in single article processing: {str(e)}"
        app.logger.error(error_msg)
        return {'error': str(e)}
    

@app.route('/process_single', methods=['POST'])
@login_required
def process_single_article():
    """Process a single article and return results"""
    try:
        # Get form data
        article_title = request.form.get('article_title', '')
        article_desc = request.form.get('article_desc', '')
        article_content = request.form.get('article_content', '')

        # Validate required fields
        if not article_title or not article_content:
            flash('Le titre et le contenu de l\'article sont obligatoires.', 'error')
            return redirect(url_for('single_article'))
        
        # Get model selection
        selected_model = request.form.get('model', 'gpt-5')

        # Get GPT-4 parameters (will be ignored for GPT-5)
        max_tokens = int(request.form.get('max_tokens', 1500))
        temperature = float(request.form.get('temperature', 0.7))
        top_p = float(request.form.get('top_p', 1.0))
        frequency_penalty = float(request.form.get('frequency_penalty', 0.0))
        presence_penalty = float(request.form.get('presence_penalty', 0.0))

        # Get GPT-5 parameters (will be ignored for GPT-4)
        max_completion_tokens = int(request.form.get('max_completion_tokens', 6000))
        reasoning_effort = request.form.get('reasoning_effort', 'medium')
        verbosity = request.form.get('verbosity', 'medium')

        # Get custom prompt
        gpt_prompt = request.form.get('gpt_prompt', '')

        app.logger.info(f"🤖 Using model: {selected_model}")

        # Load config and merge with form parameters
        config = load_config()

        # Create model-specific configuration based on user selection
        if selected_model and selected_model.startswith("gpt-5"):
            # GPT-5 configuration - only use supported parameters
            config.update({
                'model': selected_model,
                'max_completion_tokens': max_completion_tokens,
                'reasoning_effort': reasoning_effort,
                'verbosity': verbosity
            })
            
            # Remove GPT-4 specific parameters that GPT-5 doesn't support
            unsupported_params = ['max_tokens', 'temperature', 'top_p', 'frequency_penalty', 'presence_penalty']
            for param in unsupported_params:
                config.pop(param, None)
                
            print(f"🚀 Configured for GPT-5: {selected_model}")
            print(f"🚀 GPT-5 params: max_completion_tokens={max_completion_tokens}, reasoning_effort={reasoning_effort}, verbosity={verbosity}")
            app.logger.info(f"🚀 Configured for GPT-5: {selected_model}")
            app.logger.info(f"🚀 GPT-5 params: max_completion_tokens={max_completion_tokens}, reasoning_effort={reasoning_effort}, verbosity={verbosity}")

        else:
            # GPT-4 and earlier models - use traditional parameters from form
            config.update({
                'model': selected_model,
                'max_tokens': max_tokens,
                'temperature': temperature,
                'top_p': top_p,
                'frequency_penalty': frequency_penalty,
                'presence_penalty': presence_penalty
            })
            
            # Remove GPT-5 specific parameters that GPT-4 doesn't support
            unsupported_params = ['max_completion_tokens', 'reasoning_effort', 'verbosity']
            for param in unsupported_params:
                config.pop(param, None)
                
            print(f"🚀 Configured for GPT-4: {selected_model}")
            app.logger.info(f"🚀 Configured for GPT-4: {selected_model}")  
            app.logger.info(f"🚀 GPT-4 params: max_tokens={max_tokens}, temperature={temperature}")  

        # Use custom prompt if provided
        if gpt_prompt:
            config['prompt'] = gpt_prompt
        
        # Prepare article data
        article_data = {
            'title': article_title,
            'description': article_desc,
            'content': article_content
        }
        
        # Log received data (for debugging)
        print(f"📄 Article Title: {article_title[:50]}...")
        print(f"🤖 Final config model: {config.get('model')}")
        print(f"⚙️  Final config parameters: {list(config.keys())}")
        app.logger.info(f"📄 Article Title: {article_title[:50]}...")
        app.logger.info(f"🤖 Final config model: {config.get('model')}")


        if not PROCESSING_AVAILABLE:
            flash('Le traitement n\'est pas disponible. Module gem_asynchronous non trouvé.', 'error')
            app.logger.error("❌ Processing not available - gem_asynchronous module not found")
            return redirect(url_for('single_article'))
        
        # Process the article
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            result = loop.run_until_complete(
                process_single_article_async(article_data, config)
            )
        finally:
            loop.close()
        
        if 'error' in result:
            flash(f'Erreur lors du traitement: {result["error"]}', 'error')
            app.logger.error(f"❌ Single article processing failed: {result['error']}")
            return redirect(url_for('single_article'))
        
        print(f"✅ Single article processing completed!")
        app.logger.info("✅ Single article processing completed successfully!")

        # Render results page with the analysis
        return render_template('single_results.html', 
                             article_data=article_data,
                             result=result,
                             config=config)
        
    except Exception as e:
        print(f"❌ Error in process_single_article: {str(e)}")
        app.logger.error(f"❌ Error in process_single_article: {str(e)}")
        flash(f'Erreur lors du traitement: {str(e)}', 'error')
        return redirect(url_for('single_article'))

@app.route('/upload_batch', methods=['POST'])
@login_required
def upload_batch_file():
    """Upload batch file and start processing"""
    try:
        if 'file' not in request.files:
            flash('No file selected', 'error')
            app.logger.warning("⚠️ Empty filename for batch upload")
            return redirect(url_for('batch_processing'))
        
        file = request.files['file']
        if file.filename == '':
            flash('No file selected', 'error')
            return redirect(url_for('batch_processing'))
        
        if not (file and allowed_file(file.filename)):
            flash('Invalid file type. Please upload a CSV file.', 'error')
            app.logger.warning(f"⚠️ Invalid file type: {file.filename}")
            return redirect(url_for('batch_processing'))
        
        # Generate unique job ID
        job_id = str(uuid.uuid4())
        
        # Save uploaded file
        filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
        new_filename = f"{timestamp}_{job_id}_{filename}"
        input_path = os.path.join(app.config['UPLOAD_FOLDER'], new_filename)
        # input_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{job_id}_{filename}")

        file.save(input_path)
        app.logger.info(f"📁 File uploaded: {filename} -> {new_filename}")

        # Get model selection
        selected_model = request.form.get('model', 'gpt-4')

        # Get GPT-4 parameters (will be ignored for GPT-5)
        max_tokens = int(request.form.get('max_tokens', 1500))
        temperature = float(request.form.get('temperature', 0.7))
        top_p = float(request.form.get('top_p', 1.0))
        frequency_penalty = float(request.form.get('frequency_penalty', 0.0))
        presence_penalty = float(request.form.get('presence_penalty', 0.0))

        # Get GPT-5 parameters (will be ignored for GPT-4)
        max_completion_tokens = int(request.form.get('max_completion_tokens', 6000))
        reasoning_effort = request.form.get('reasoning_effort', 'medium')
        verbosity = request.form.get('verbosity', 'medium')
        
         # Get custom prompt
        custom_prompt = request.form.get('gpt_prompt', '').strip()
        
        # Get processing parameters from form
        config = load_config()  # Load base config

        # Create model-specific configuration based on user selection
        if selected_model and selected_model.startswith("gpt-5"):
            # GPT-5 configuration - use form parameters
            config.update({
                'model': selected_model,
                'max_completion_tokens': max_completion_tokens,  # Use from form
                'reasoning_effort': reasoning_effort,  # Use from form
                'verbosity': verbosity  # Use from form
            })
            
            # Remove GPT-4 specific parameters that GPT-5 doesn't support
            unsupported_params = ['max_tokens', 'temperature', 'top_p', 'frequency_penalty', 'presence_penalty']
            for param in unsupported_params:
                config.pop(param, None)
                
            print(f"🚀 Batch configured for GPT-5: {selected_model}")
            print(f"🚀 GPT-5 params: max_completion_tokens={max_completion_tokens}, reasoning_effort={reasoning_effort}, verbosity={verbosity}")
            app.logger.info(f"🚀 Batch configured for GPT-5: {selected_model}")

        else:
            # GPT-4 and earlier models - use traditional parameters from form
            config.update({
                'model': selected_model,
                'max_tokens': max_tokens,
                'temperature': temperature,
                'top_p': top_p,
                'frequency_penalty': frequency_penalty,
                'presence_penalty': presence_penalty
            })
            
            # Remove GPT-5 specific parameters that GPT-4 doesn't support
            unsupported_params = ['max_completion_tokens', 'reasoning_effort', 'verbosity']
            for param in unsupported_params:
                config.pop(param, None)
                
            print(f"🚀 Batch configured for GPT-4: {selected_model}")
            print(f"🚀 GPT-4 params: max_tokens={max_tokens}, temperature={temperature}")
            app.logger.info(f"🚀 Batch configured for GPT-4: {selected_model}")
        
        # Use custom prompt if provided
        if custom_prompt:
            config['prompt'] = custom_prompt
        
        # Initialize job status
        processing_jobs[job_id] = {
            'status': 'queued',
            'progress': 0,
            'total_articles': 0,
            'processed_articles': 0,
            'start_time': datetime.now(),
            'end_time': None,
            'input_file': input_path,
            'input_filename': filename,
            'output_file': None,
            'error': None,
            'config': config
        }
        
        # Start processing in background thread
        thread = threading.Thread(target=process_batch_async, args=(job_id,))
        thread.daemon = True
        thread.start()
        
        print(f"🚀 Started batch processing job {job_id} for file {filename}")
        app.logger.info(f"🚀 Started batch processing job {job_id} for file {filename}")
        
        # Redirect to status page
        return redirect(url_for('batch_status', job_id=job_id))
        
    except Exception as e:
        print(f"❌ Error in upload_batch_file: {str(e)}")
        app.logger.error(f"❌ Error in upload_batch_file: {str(e)}")
        flash(f'Error uploading file: {str(e)}', 'error')
        return redirect(url_for('batch_processing'))
    
    
@app.route('/download-template')
@login_required
def download_template():
    app.logger.info("📥 Template download requested")
    template_path = os.path.join(app.root_path, 'inputTemplate', 'input.csv')
    return send_file(template_path, as_attachment=True, download_name='input_template.csv')

@app.route('/batch_status/<job_id>')
@login_required
def batch_status(job_id):
    """Show batch processing status page"""
    if job_id not in processing_jobs:
        app.logger.warning(f"⚠️ Job not found: {job_id}")
        flash('Job not found', 'error')
        return redirect(url_for('batch_processing'))
    
    app.logger.info(f"📊 Status page accessed for job: {job_id}")
    job = processing_jobs[job_id]
    return render_template('batch_status.html', job=job, job_id=job_id)

@app.route('/api/job_status/<job_id>')
@login_required
def api_job_status(job_id):
    """API endpoint for real-time job status updates"""
    if job_id not in processing_jobs:
        app.logger.warning(f"⚠️ API status request for unknown job: {job_id}")
        return jsonify({'error': 'Job not found'}), 404
    
    job = processing_jobs[job_id]
    
    # Calculate duration if job is running
    duration = None
    if job['start_time']:
        end_time = job['end_time'] if job['end_time'] else datetime.now()
        duration = int((end_time - job['start_time']).total_seconds())
    
    return jsonify({
        'status': job['status'],
        'progress': job['progress'],
        'processed_articles': job['processed_articles'],
        'total_articles': job['total_articles'],
        'error': job['error'],
        'duration': duration,
        'input_filename': job['input_filename']
    })

@app.route('/download/<job_id>')
@login_required
def download_results(job_id):
    """Download processing results"""
    if job_id not in processing_jobs:
        app.logger.warning(f"⚠️ Download request for unknown job: {job_id}")
        flash('Job not found', 'error')
        return redirect(url_for('batch_processing'))
    
    job = processing_jobs[job_id]
    if job['status'] != 'completed' or not job['output_file']:
        app.logger.warning(f"⚠️ Download request for incomplete job: {job_id}")
        flash('Results not ready for download', 'error')
        return redirect(url_for('batch_status', job_id=job_id))
    
    if not os.path.exists(job['output_file']):
        app.logger.error(f"❌ Output file not found for job: {job_id}")
        flash('Output file not found', 'error')
        return redirect(url_for('batch_status', job_id=job_id))
    
    # Generate download filename
    output_filename = os.path.basename(job['output_file'])
    app.logger.info(f"📥 Results downloaded for job: {job_id}")
    
    return send_file(
        job['output_file'], 
        as_attachment=True, 
        download_name=output_filename,
        mimetype='text/csv'
    )

@app.route('/cancel_job/<job_id>', methods=['POST'])
@login_required
def cancel_job(job_id):
    """Cancel a running job with proper backend cancellation"""
    if job_id in processing_jobs:
        print(f"🛑 Cancelling job {job_id}")
        app.logger.warning(f"🛑 Cancelling job {job_id}")
        
        # Set job status to cancelled
        processing_jobs[job_id]['status'] = 'cancelled'
        processing_jobs[job_id]['end_time'] = datetime.now()
        
        # Signal the cancellation event if it exists
        if job_id in job_cancellation_events:
            job_cancellation_events[job_id].set()
            print(f"🛑 Cancellation signal sent for job {job_id}")
            app.logger.info(f"🛑 Cancellation signal sent for job {job_id}")
        
        flash('Job cancelled successfully', 'info')
    else:
        app.logger.warning(f"⚠️ Cancel request for unknown job: {job_id}")
        flash('Job not found', 'error')
    
    return redirect(url_for('batch_processing'))
    


if __name__ == '__main__':
    print("🚀 Starting Flask application...")
    print(f"📁 Upload folder: {UPLOAD_FOLDER}")
    print(f"📁 Output folder: {OUTPUT_FOLDER}")
    print("🌐 Access the app at: http://localhost:5000")
    app.logger.info("🚀 Starting Flask application...")
    app.logger.info(f"📁 Upload folder: {UPLOAD_FOLDER}")
    app.logger.info(f"📁 Output folder: {OUTPUT_FOLDER}")
    app.logger.info("🌐 Access the app at: http://localhost:5000")
    app.run(debug=False, host='0.0.0.0', port=5000)