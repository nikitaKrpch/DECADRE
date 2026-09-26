import asyncio
import aiofiles
import csv
import pandas as pd
import spacy
from spacy.language import Language
from spacy_lefff import LefffLemmatizer, POSTagger
from openai import AsyncOpenAI
import yaml
import re
import os
import nest_asyncio
from nltk import ngrams
import tiktoken
import string
import unicodedata
import re
from nltk.stem.snowball import FrenchStemmer
import logging


# Apply nest_asyncio to allow re-entrance in Jupyter or similar environments
nest_asyncio.apply()

# Set up logger for this module
logger = None

def set_logger(processing_logger):
    """Set the logger for this module"""
    global logger
    logger = processing_logger
    logger.info("🔗 Logger configured for gem_asynchronous module")
    
    # Now we can log the spaCy model status
    if nlp is not None:
        logger.info("✅ SpaCy French model loaded successfully")
    else:
        logger.error("❌ fr_core_news_sm not found. Please install: python -m spacy download fr_core_news_sm")

# Load the spaCy French language model
try:
    nlp = spacy.load("fr_core_news_sm")
except OSError:
    print("⚠️  fr_core_news_sm not found. Please install: python -m spacy download fr_core_news_sm")
    nlp = None

# Initialize NLTK French stemmer
stemmer = FrenchStemmer()

# Initialize OpenAI client (will be set with API key later)
openai_client = None
# Optional second client used when the primary key fails (e.g. busy shared key)
fallback_client = None

def set_openai_api_key(api_key):
    """Set the OpenAI API key (base URL comes from OPENAI_BASE_URL if set)"""
    global openai_client, fallback_client
    # max_retries=1: retry a refused request once before giving up on this key
    openai_client = AsyncOpenAI(api_key=api_key, max_retries=1)
    fallback_key = os.getenv("OPENAI_API_KEY_FALLBACK")
    fallback_client = AsyncOpenAI(api_key=fallback_key, max_retries=1) if fallback_key else None
    logger.info(f"🔑 API key configured (fallback key: {'yes' if fallback_client else 'no'})")

def load_yaml_config(path):
    try:
        with open(path, 'r', encoding='utf-8') as file:
            content = file.read()
            return yaml.load(content, Loader=yaml.FullLoader)
    except Exception as e:
        print(f"Error loading YAML config file {path}: {e}")
        logger.error(f"❌ Error loading YAML config file {path}: {e}")
        return None

# CSV file reading using pandas (no native async support)
def load_csv(path):
    try:
        return pd.read_csv(path, encoding='utf-8-sig')
    except Exception as e:
        logger.error(f"❌ Error loading CSV file {path}: {e}")
        print(f"Error loading CSV file {path}: {e}")
        return None

# Get Model's Max Tokens
def get_model_max_tokens(model_name):
    model_max_context = {
        "gpt-3.5-turbo": 4096,
        "gpt-3.5-turbo-16k": 16384,
        "gpt-4": 8192,
        "gpt-4-32k": 32768,
        "gpt-4-turbo": 128000,
        "gpt-4o": 128000,
        "gpt-5": 131072,          # 128k context
        "gpt-5-mini": 65536,      # 65k context
        "gpt-5-nano": 32768,       # 32k context
        "gpt-5-chat-latest": 131072,
        # EPFL inference endpoint (hackathon)
        "openai/gpt-oss-120b": 131072,
        "swiss-ai/Apertus-v1.5-70B": 65536,
        # Add other models if needed
    }
    return model_max_context.get(model_name, 4096)  # Default to 4096 if model not found

# Count the number of tokens in the combined prompt and article text:
def count_tokens(text, model_name):
    try:
        try:
            encoding = tiktoken.encoding_for_model(model_name)
            logger.debug(f"🔢 Using direct tokenizer for {model_name}")
        except KeyError:
            # fallback for newer models not registered in tiktoken yet
            encoding = tiktoken.get_encoding("cl100k_base")
            logger.debug(f"🔄 Using cl100k_base fallback tokenizer for {model_name}")
        
        tokens = encoding.encode(text)
        token_count = len(tokens)
        logger.debug(f"🔢 Token count for {model_name}: {token_count}")
        return token_count
        
    except Exception as e:
        print(f"⚠️ Error counting tokens for {model_name}: {e}")
        logger.warning(f"⚠️ Error counting tokens for {model_name}: {e}, using estimation")
        # Fallback estimation
        estimated_tokens = int(len(text.split()) * 0.75)
        logger.debug(f"📊 Estimated tokens: {estimated_tokens}")
        return estimated_tokens

# Updated asynchronous API call to OpenAI with new library
async def classify_categories_with_chatGPT(prompt, text, config, cancellation_event=None):
    global openai_client
    
    if not openai_client:
        print("❌ OpenAI client not initialized. Please set API key.")
        logger.error("❌ OpenAI client not initialized. Please set API key.")
        return None
    
    # Check for cancellation before making API call
    if cancellation_event and cancellation_event.is_set():
        print("🛑 GPT request cancelled before API call")
        logger.warning("🛑 GPT request cancelled before API call")
        return None
    
    try:
        model = config.get("model", "gpt-5")
        logger.debug(f"🤖 Making OpenAI API call with model: {model}")

        # Prepare the base parameters
        params = {
            "model": model,
            "messages": [
                {"role": "system", "content": "Bonjour, vous êtes un expert en sociologie."},
                {"role": "user", "content": f"{prompt}{text}"}
            ]
        }
        
        # Handle parameters based on model type
        if model and model.startswith("gpt-5"):
            # GPT-5 models: Only certain parameters are supported
            params["max_completion_tokens"] = config.get("max_completion_tokens", 6000)
            
            # GPT-5 specific parameters (if provided)
            if config.get("reasoning_effort"):
                params["reasoning_effort"] = config.get("reasoning_effort")
            if config.get("verbosity"):
                params["verbosity"] = config.get("verbosity")
            
            print(f"🚀 Using GPT-5 with max_completion_tokens: {params['max_completion_tokens']}")
            logger.debug(f"🚀 Using GPT-5 with max_completion_tokens: {params['max_completion_tokens']}")
            
        else:
            # GPT-4 and earlier models: Use all traditional parameters
            params["max_tokens"] = config.get("max_tokens", 1500)
            params["temperature"] = config.get("temperature", 0.3)
            params["top_p"] = config.get("top_p", 0.7)
            params["frequency_penalty"] = config.get("frequency_penalty", 0.5)
            params["presence_penalty"] = config.get("presence_penalty", 0.0)
            
            print(f"🚀 Using GPT-4 with max_tokens: {params['max_tokens']}")
            logger.debug(f"🚀 Using GPT-4 with max_tokens: {params['max_tokens']}")

        # Use the new asynchronous OpenAI API call, falling back to the second key if the first fails
        try:
            response = await openai_client.chat.completions.create(**params)
        except Exception as e:
            if not fallback_client:
                raise
            print(f"⚠️ Primary API key failed ({e}), retrying with fallback key")
            logger.warning(f"⚠️ Primary API key failed ({e}), retrying with fallback key")
            response = await fallback_client.chat.completions.create(**params)

        # Check for cancellation after API call
        if cancellation_event and cancellation_event.is_set():
            print("🛑 GPT request cancelled after API call")
            logger.warning("🛑 GPT request cancelled after API call")
            return None

        # Debug information
        print(f"✅ API Response received for article using {response.model}")
        logger.debug(f"✅ API Response received successfully using {response.model}")
        
        # Log token usage
        usage = response.usage
        print(f"📊 Token usage - Prompt: {usage.prompt_tokens}, Completion: {usage.completion_tokens}")
        logger.debug(f"📊 Token usage - Prompt: {usage.prompt_tokens}, Completion: {usage.completion_tokens}")
        
        # Log reasoning tokens for GPT-5
        if hasattr(usage, 'completion_tokens_details') and usage.completion_tokens_details:
            reasoning_tokens = usage.completion_tokens_details.reasoning_tokens
            if reasoning_tokens > 0:
                print(f"🧠 Reasoning tokens: {reasoning_tokens}")
                logger.debug(f"🧠 Reasoning tokens: {reasoning_tokens}")

        # Get the response content
        content = response.choices[0].message.content
        
        if not content:
            print("⚠️ Warning: Empty response received")
            logger.warning("⚠️ Warning: Empty response received")
            return None
            
        return content.strip()

    except Exception as e:
        # Check if this is due to cancellation
        if cancellation_event and cancellation_event.is_set():
            print("🛑 GPT request cancelled due to exception")
            logger.warning("🛑 GPT request cancelled due to exception")
            return None
        
        print(f"❌ OpenAI error occurred: {e}")
        logger.error(f"❌ OpenAI error occurred: {e}")
        
        # Additional error context for debugging
        if "max_completion_tokens" in str(e):
            print("💡 Hint: Try reducing max_completion_tokens or max_tokens")
            logger.error("💡 Hint: Try reducing max_completion_tokens or max_tokens")
        elif "temperature" in str(e) and model.startswith("gpt-5"):
            print("💡 Hint: GPT-5 doesn't support temperature parameter")
            logger.error("💡 Hint: GPT-5 doesn't support temperature parameter")
        
        return None
'''
async def classify_categories_with_chatGPT(prompt, text, config, cancellation_event=None):
    global openai_client
    
    if not openai_client:
        print("❌ OpenAI client not initialized. Please set API key.")
        logger.error("❌ OpenAI client not initialized. Please set API key.")
        return None
    
    # Check for cancellation before making API call
    if cancellation_event and cancellation_event.is_set():
        print("🛑 GPT request cancelled before API call")
        logger.warning("🛑 GPT request cancelled before API call")
        return None
    
    try:
        logger.debug("🤖 Making OpenAI API call...")

        # Use the new asynchronous OpenAI API call
        response = await openai_client.chat.completions.create(
            model=config.get("model", "gpt-4"),
            messages=[
                {"role": "system", "content": "Bonjour, vous êtes un expert en sociologie."},
                {"role": "user", "content": f"{prompt}{text}"}
            ],
            max_tokens=config.get("max_tokens", 1500),
            temperature=config.get("temperature", 0.3),
            top_p=config.get("top_p", 0.7),
            frequency_penalty=config.get("frequency_penalty", 0.5),
            presence_penalty=config.get("presence_penalty", 0.0)
        )

         # Check for cancellation after API call
        if cancellation_event and cancellation_event.is_set():
            print("🛑 GPT request cancelled after API call")
            logger.warning("🛑 GPT request cancelled after API call")
            return None

        # Log the response for debugging
        print(f"✅ API Response received for article")
        logger.debug("✅ API Response received successfully")

        # Extract and return the response message content
        return response.choices[0].message.content.strip()

    except Exception as e:
        # Check if this is due to cancellation
        if cancellation_event and cancellation_event.is_set():
            print("🛑 GPT request cancelled due to exception")
            logger.warning("🛑 GPT request cancelled due to exception")
            return None
        print(f"❌ OpenAI error occurred: {e}")
        logger.error(f"❌ OpenAI error occurred: {e}")
        return None
'''

def stem_text(text):
    if not nlp:
        # Fallback if spaCy model not available
        logger.warning("⚠️ SpaCy model not available, using basic tokenization")
        return text.lower().split()
    
    # Normalize accented characters
    text_normalized = unicodedata.normalize('NFC', text)
    # Remove punctuation (including French-specific punctuation)
    text_no_punct = re.sub(r'[^\w\s]', ' ', text_normalized)
    # Convert text to lowercase
    text_lower = text_no_punct.lower()
    # Tokenize text using SpaCy French tokenizer
    doc = nlp(text_lower)
    stems = []
    for token in doc:
        if token.is_upper:
            # Preserve acronyms (e.g., 'AFP')
            stems.append(token.text.lower())
        else:
            # Stem the token using French stemmer
            stem = stemmer.stem(token.text)
            stems.append(stem)
    return stems

# Load corpora from files
def load_corpora(corpora_files):
    corpora = {}
    for file_path in corpora_files:
        try:
            # Check if the file exists
            if not os.path.isfile(file_path):
                print(f"⚠️  File not found: {file_path}")
                logger.warning(f"⚠️ File not found: {file_path}")
                continue

            # Open and read the file synchronously
            with open(file_path, 'r', encoding='utf-8-sig') as file:
                corpus_name = os.path.basename(file_path).replace(".txt", "")
                lines = file.readlines()

                # Strip any extra whitespace or newlines
                corpora[corpus_name] = [line.strip() for line in lines if line.strip()]
                print(f"📚 Loaded corpus: {corpus_name} ({len(corpora[corpus_name])} items)")
                logger.info(f"📚 Loaded corpus: {corpus_name} ({len(corpora[corpus_name])} items)")

        except Exception as e:
            print(f"❌ Error loading corpus file {file_path}: {e}")
            logger.error(f"❌ Error loading corpus file {file_path}: {e}")

    print(f"📖 Total corpora loaded: {len(corpora)}")
    logger.info(f"📖 Total corpora loaded: {len(corpora)}")
    return corpora

def count_corpus_occurrences(text, corpus):
    if not corpus:
        return 0, []
    
    # Stem the article text
    article_stems = stem_text(text)
    # Generate n-grams from article stems
    max_phrase_length = max(len(phrase.split()) for phrase in corpus)
    article_ngrams = set()
    for n in range(1, max_phrase_length + 1):
        ngrams_list = [
            ' '.join(article_stems[i:i + n]) 
            for i in range(len(article_stems) - n + 1)
        ]
        article_ngrams.update(ngrams_list)
    # Stem the corpus phrases
    corpus_stems = []
    for phrase in corpus:
        phrase_stems = stem_text(phrase)
        normalized_phrase_stems = ' '.join(phrase_stems)
        corpus_stems.append(normalized_phrase_stems)
    # Initialize a set to avoid duplicate matches
    matching_phrases = set()
    
    for original_phrase, stem_phrase in zip(corpus, corpus_stems):
        # Special handling for "parlement" - require exact word match
        if original_phrase.lower() == "parlement":
            # Use regex to find whole word matches only
            pattern = r'\bparlement\b'
            if re.search(pattern, text.lower()):
                print(f"Exact match found for: {original_phrase}")
                matching_phrases.add(original_phrase)
        else:
            # Normal stemming logic for all other words
            if stem_phrase in article_ngrams:
                #print(stem_phrase)
                matching_phrases.add(original_phrase)
    
    count = len(matching_phrases)
    return count, list(matching_phrases)

# Function for calculating the size of article
def character_count(text):
    return len(text)

def classify_conditional_verbs(text, corpora):
    if not nlp:
        return 0, []
    
    # Process the text
    doc = nlp(text)
    
    # Initialize counters
    total_verbs = 0
    conditional_verbs = 0
    conditional_verbs_list = []        
    
    # Iterate through tokens and count conditional verbs
    for token in doc:
        if token.pos_ == 'VERB':
            total_verbs += 1
            # Check if the verb is in conditional mood
            if any(token.text.endswith(ending) for ending in corpora.get("verb_conditional", [])):  
                conditional_verbs += 1
                conditional_verbs_list.append(token.text)
    
    print(f"📊 Conditional verbs: {conditional_verbs}/{total_verbs}")
    logger.debug(f"📊 Conditional verbs: {conditional_verbs}/{total_verbs}")

    if conditional_verbs > 0:
        proportion = conditional_verbs / total_verbs
    else:
        proportion = 0.0

    # Classify based on the proportion
    if proportion <= 0.25:
        classification = 1   # Display 1 when proportion is less than or equal to 0.25
    elif proportion > 0.5:
        classification = -1   # Display -1 when proportion is greater than 0.5
    else:
        classification = 0  # Display 0 when proportion is less than or equal to 0.5, but more than 0.25

    return classification, conditional_verbs_list

# Extract the option numbers along with their corresponding text from ChatGPT results
def extract_chatGPT_results(chatGPT_results):
    pattern = r"Question\s*(\d+)\s*[:\-]?\s*Option\s*[:]?[\s]*(\-?\d+)\s*[\.]?\s*(.*)"

    # Find all matches in the input text
    matches = re.finditer(pattern, chatGPT_results, re.IGNORECASE)
    
    # Initialize a list to store the extracted information
    extracted_info = []
    
    # Iterate through the matches and store them in the list
    for match in matches:
        # Extract the number, option, and text for each match
        question_number = int(match.group(1))
        option_number = int(match.group(2))
        explication = match.group(3).strip()
        # Remove leading punctuation and whitespace from the explanation
        explication = explication.lstrip(string.punctuation + ' ').strip()
        
        # Append the extracted information as a dictionary to the list
        extracted_info.append({
            "question_number": question_number,
            "option_number": option_number,
            "explication": explication
        })
    
    logger.debug(f"📝 Extracted {len(extracted_info)} ChatGPT results")
    return extracted_info
    
def safe_lower(text):
    return text.lower() if isinstance(text, str) else ''

# Updated asynchronous article processing function with progress tracking and cancellation support
async def process_article(index, row, corpora, config, big_article, semaphore, progress_callback=None, cancellation_event=None):
    try:
        # Check for cancellation at the start
        if cancellation_event and cancellation_event.is_set():
            print(f"🛑 Article {index+1} processing cancelled before start")
            logger.warning(f"🛑 Article {index+1} processing cancelled before start")
            if progress_callback:
                progress_callback(index, "cancelled")
            return None
        
        # Initialize these variables at the start of the function
        is_soustendent_violences = False
        is_in_vocabulaire_violence = False
        
        article_body = (
            safe_lower(row.get("article_title", "")) + " " +
            safe_lower(row.get("article_desc", "")) + " " +
            safe_lower(row.get("article_content", ""))
        )
        
        article_count_characters = len(article_body)
        print(f"🔄 Processing article {index+1}, characters: {article_count_characters}")
        logger.info(f"🔄 Processing article {index+1}, characters: {article_count_characters}")

        # Call progress callback if provided
        if progress_callback:
            # Check if callback returns False (indicating cancellation)
            if progress_callback(index, "processing") == False:
                print(f"🛑 Article {index+1} processing cancelled by callback")
                logger.warning(f"🛑 Article {index+1} processing cancelled by callback")
                return None

        # Initialize a dictionary to store results for this article
        result = {'index': index}

        # List of all expected keys in the result dictionary
        result_keys = [
            # NLP results
            'agence', 'agence_ex', 'en_lien_avec_affaire', 'en_lien_avec_affaire_ex', 'mention_feminicide', 'mention_feminicide_ex', 
            'vocabulaire', 'vocs_violence_ex', 'vocs_minimisant_ex', 
            'sante_mentale', 'sante_mentale_ex', 'substance_psychotrope', 'substance_psychotrope_ex', 'animalisant', 'animalisant_ex', 
            'sideration', 'sideration_ex', 'desc_agresseur', 'desc_agresseur_ex', 
            'culture_du_viol', 'culture_du_viol_ex', 'validite', 'validite_ex', 'taille', 'taille_ex', 'classification_result',
            'soustendent_violences', 'soustendent_violences_ex',

            # Results from ChatGPT processing
            'type_violence', 'type_violence_ex',
            'cadre_violence', 'cadre_violence_ex',
            'feminicide', 'feminicide_ex',
            'sources', 'sources_ex',
            'hierarchisation', 'hierarchisation_ex',
            'desc_victime', 'desc_victime_ex',
            'nationalite_auteur', 'nationalite_auteur_ex',
            'nationalite_victime', 'nationalite_victime_ex',
            'nationalite_suisse_auteur', 'nationalite_suisse_auteur_ex',
            'nationalite_suisse_victime', 'nationalite_suisse_victime_ex',
            'desc_relation_protagonistes', 'desc_relation_protagonistes_ex',
            'type_relation_protagonistes', 'type_relation_protagonistes_ex',
            'escalade_violences', 'escalade_violences_ex',
            'statistiques', 'statistiques_ex',
            'autres_violences', 'autres_violences_ex',
            'citations', 'citations_ex',
            'ressources', 'ressources_ex',
            'consequences_auteur', 'consequences_auteur_ex',
            'consequences_victime', 'consequences_victime_ex',
            'motif_violence', 'motif_violence_ex',
        ]

        # Initialize default values for all expected keys
        for key in result_keys:
            result[key] = '-'

        # Check for cancellation before starting NLP processing
        if cancellation_event and cancellation_event.is_set():
            print(f"🛑 Article {index+1} processing cancelled before NLP analysis")
            logger.warning(f"🛑 Article {index+1} processing cancelled before NLP analysis")
            if progress_callback:
                progress_callback(index, "cancelled")
            return None
    
        logger.debug(f"🔍 Starting NLP analysis for article {index+1}")

        # Article provient d'une agence
        agence, agence_matches = count_corpus_occurrences(article_body, [word.lower() for word in corpora.get("agence", [])])       
        result['agence'] = 1 if agence > 0 else 2
        result['agence_ex'] = ', '.join(agence_matches) if agence_matches else '-'
    
        # En lien avec une affaire
        lien, lien_matches = count_corpus_occurrences(article_body, [word.lower() for word in corpora.get("en lien avec une affaire", [])])
        lien_exclu, lien_exclu_matches = count_corpus_occurrences(article_body, [word.lower() for word in corpora.get("en lien avec une affaire exclue", [])])
    
        # Check if the article contains keywords in 'lien' but not in 'lien_exclu'
        if lien > 0 and lien_exclu == 0:
            result['en_lien_avec_affaire'] = 1
        else:
            result['en_lien_avec_affaire'] = 2

        # Combine matches for inclusion in the result
        lien_ex_matches_combined = (
            f"Lien matches: {', '.join(lien_matches)}" if lien_matches else "Lien matches: -"
        ) + " | " + (
            f"Lien exclu matches: {', '.join(lien_exclu_matches)}" if lien_exclu_matches else "Lien exclu matches: -"
        )
        result['en_lien_avec_affaire_ex'] = lien_ex_matches_combined
        
        # Féminicide / mention féminicide
        mention_feminicide, mention_feminicide_matches = count_corpus_occurrences(article_body, [word.lower() for word in corpora.get("mention_feminicide", [])])
        if mention_feminicide > 0:
            result['mention_feminicide'] = 1
        else:
            result['mention_feminicide'] = 2

        result['mention_feminicide_ex'] = ', '.join(mention_feminicide_matches) if mention_feminicide_matches else '-'
    
        # Le vocabulaire 
        vocs_violence, vocs_violence_matches = count_corpus_occurrences(article_body, [word.lower() for word in corpora.get("vocabulaire_violence", [])])
        vocs_minimisant, vocs_minimisant_matches = count_corpus_occurrences(article_body, [word.lower() for word in corpora.get("vocabulaire_minimisant", [])])
    
        if vocs_violence > 0:
            is_in_vocabulaire_violence = True
        
        if vocs_violence > 0 and vocs_minimisant == 0:
            result['vocabulaire'] = 1
        elif vocs_minimisant > vocs_violence:    
            result['vocabulaire'] = -1
        else:
            result['vocabulaire'] = 0

        result['vocs_violence_ex'] = ', '.join(vocs_violence_matches) if vocs_violence_matches else '-'
        result['vocs_minimisant_ex'] = ', '.join(vocs_minimisant_matches) if vocs_minimisant_matches else '-'

        # Continue with all your existing NLP analysis...
        # (I'll include the key parts, you can copy the rest from your original code)
           
        # Mention de la santé mentale de l'auteur
        sante_mentale, sante_mentale_matches = count_corpus_occurrences(article_body, [word.lower() for word in corpora.get("sante mentale", [])])
        result['sante_mentale'] = 1 if sante_mentale > 0 else 2
        result['sante_mentale_ex'] = ', '.join(sante_mentale_matches) if sante_mentale_matches else '-'

        # Mention des substances psychotropes
        substance_psychotrope, substance_psychotrope_matches = count_corpus_occurrences(article_body, [word.lower() for word in corpora.get("substance psychotrope", [])])
        result['substance_psychotrope'] = 1 if substance_psychotrope > 0 else 2
        result['substance_psychotrope_ex'] = ', '.join(substance_psychotrope_matches) if substance_psychotrope_matches else '-'

        # Mention d'une forme d'animalisation 
        animalisant, animalisant_matches = count_corpus_occurrences(article_body, [word.lower() for word in corpora.get("animalisant", [])])
        result['animalisant'] = 1 if animalisant > 0 else 2
        result['animalisant_ex'] = ', '.join(animalisant_matches) if animalisant_matches else '-'

        # Determine 'desc_agresseur' based on the values of the three elements
        if substance_psychotrope > 0 or animalisant > 0 or sante_mentale > 0:
            result['desc_agresseur'] = 0
        else:
            result['desc_agresseur'] = 1
        # Create the explanation strings
        substance_psychotrope_bol = "Substance psychotrope: " + ("Oui" if substance_psychotrope > 0 else "Non")
        animalisant_bol = "Animalisant: " + ("Oui" if animalisant > 0 else "Non")
        sante_mentale_bol = "Santé mentale: " + ("Oui" if sante_mentale > 0 else "Non")
        # Combine the explanations into one string
        result['desc_agresseur_ex'] = ', '.join([substance_psychotrope_bol, animalisant_bol, sante_mentale_bol])

        # Mention du processus de sidération 
        sideration, sideration_matches = count_corpus_occurrences(article_body, [word.lower() for word in corpora.get("sideration", [])])
        if sideration > 0:
            result['sideration'] = 1
            is_soustendent_violences = True
        else:
            result['sideration'] = 2
        result['sideration_ex'] = ', '.join(sideration_matches) if sideration_matches else '-'

        # Mention de la culture du viol / objetisation / sexisme
        culture_du_viol, culture_du_viol_matches = count_corpus_occurrences(article_body, [word.lower() for word in corpora.get("culture du viol", [])])
        if culture_du_viol > 0:
            result['culture_du_viol'] = 1 
            is_soustendent_violences = True
        else:
            result['culture_du_viol'] = 2
        result['culture_du_viol_ex'] = ', '.join(culture_du_viol_matches) if culture_du_viol_matches else '-'

        # La validité des informations 
        validite, conditional_verbs_list = classify_conditional_verbs(article_body, corpora)
        result['validite'] = validite 
        result['validite_ex'] = ', '.join(conditional_verbs_list) if conditional_verbs_list else '-'

        # La taille d'article
        char_count = character_count(article_body)
        if char_count <= 1000:
            result['taille'] = 1
        elif char_count <= 4000:
            result['taille'] = 2
        else:
            result['taille'] = 3

        result['taille_ex'] = char_count

        # Determine 'soustendent_violences' after processing relevant fields
        if is_soustendent_violences:
            result['soustendent_violences'] = 1
        elif is_in_vocabulaire_violence:
            result['soustendent_violences'] = 0
        else:
            result['soustendent_violences'] = -1

        # Check for cancellation before GPT processing
        if cancellation_event and cancellation_event.is_set():
            print(f"🛑 Article {index+1} processing cancelled before GPT analysis")
            logger.warning(f"🛑 Article {index+1} processing cancelled before GPT analysis")
            if progress_callback:
                progress_callback(index, "cancelled")
            return None

        # Get model parameters
        model_name = config.get("model")

        # Handle max tokens based on model type
        if model_name and model_name.startswith("gpt-5"):
            # GPT-5 uses max_completion_tokens
            max_tokens = config.get("max_completion_tokens", 6000)
            print(f"🤖 Using GPT-5 with max_completion_tokens: {max_tokens}")
            logger.debug(f"🤖 Using GPT-5 with max_completion_tokens: {max_tokens}")
        else:
            # GPT-4 and earlier use max_tokens
            max_tokens = config.get("max_tokens", 1500)
            print(f"🤖 Using GPT-4 with max_tokens: {max_tokens}")
            logger.debug(f"🤖 Using GPT-4 with max_tokens: {max_tokens}")
    
        # Combine prompt and article body
        prompt = config.get("prompt")
        combined_text = f"{prompt}{article_body}"
    
         # Count tokens
        input_tokens = count_tokens(combined_text, model_name)
        print(f"📊 Input tokens: {input_tokens}")
        logger.debug(f"📊 Input tokens: {input_tokens}")

        # Ensure max_tokens is not None before adding
        if max_tokens is None:
            max_tokens = 6000 if model_name and model_name.startswith("gpt-5") else 1500
            print(f"⚠️  max_tokens was None, using fallback: {max_tokens}")
            logger.warning(f"⚠️  max_tokens was None, using fallback: {max_tokens}")
    
        total_tokens = input_tokens + max_tokens  # Total tokens including expected output  
        print(f"📊 Total tokens: {total_tokens}")
        logger.debug(f"📊 Total tokens: {total_tokens}")
    
        # Get the model's maximum context length
        model_max_tokens = get_model_max_tokens(model_name)

        # Initialize final status - will be set at the end
        final_status = "completed"
        
        # If the article meets the criteria, classify with GPT asynchronously
        if total_tokens < model_max_tokens:
            # Check for cancellation before API call
            if cancellation_event and cancellation_event.is_set():
                print(f"🛑 Article {index+1} processing cancelled before GPT API call")
                logger.warning(f"🛑 Article {index+1} processing cancelled before GPT API call")
                if progress_callback:
                    progress_callback(index, "cancelled")
                return None
            
            # Use the semaphore to limit concurrent API calls
            async with semaphore:
                # Check cancellation again inside semaphore
                if cancellation_event and cancellation_event.is_set():
                    print(f"🛑 Article {index+1} processing cancelled inside semaphore")
                    logger.warning(f"🛑 Article {index+1} processing cancelled inside semaphore")
                    if progress_callback:
                        progress_callback(index, "cancelled")
                    return None
                
                chatGPT_response = await classify_categories_with_chatGPT(prompt, article_body, config, cancellation_event)

            # Check for cancellation after API call
            if cancellation_event and cancellation_event.is_set():
                print(f"🛑 Article {index+1} processing cancelled after GPT API call")
                logger.warning(f"🛑 Article {index+1} processing cancelled after GPT API call")
                if progress_callback:
                    progress_callback(index, "cancelled")
                return None
            
            if chatGPT_response:
                result['classification_result'] = chatGPT_response
                logger.debug(f"✅ GPT analysis completed for article {index+1}")

                # Process the ChatGPT result, extract options, and append to result lists
                options = extract_chatGPT_results(chatGPT_response)
           
                for option_info in options:
                    question_number = option_info.get("question_number")
                    option_number = int(option_info.get("option_number", 0))
                    explication = option_info.get("explication", "").strip()
    
                    if question_number == 1:
                        result['type_violence'] = option_number
                        result['type_violence_ex'] = explication
                    elif question_number == 2:
                        result['cadre_violence'] = option_number
                        result['cadre_violence_ex'] = explication
                    elif question_number == 3:
                        result['feminicide'] = option_number
                        result['feminicide_ex'] = explication
                    elif question_number == 4:
                        result['sources'] = option_number
                        result['sources_ex'] = explication
                    elif question_number == 5:
                        result['hierarchisation'] = option_number
                        result['hierarchisation_ex'] = explication
                    elif question_number == 6:
                        result['desc_victime'] = option_number
                        result['desc_victime_ex'] = explication
                    elif question_number == 7:
                        result['nationalite_auteur'] = option_number
                        result['nationalite_auteur_ex'] = explication
                    elif question_number == 8:
                        result['nationalite_victime'] = option_number
                        result['nationalite_victime_ex'] = explication
                    elif question_number == 9:
                        result['nationalite_suisse_auteur'] = option_number
                        result['nationalite_suisse_auteur_ex'] = explication
                    elif question_number == 10:
                        result['nationalite_suisse_victime'] = option_number
                        result['nationalite_suisse_victime_ex'] = explication
                    elif question_number == 11:
                        result['desc_relation_protagonistes'] = option_number
                        result['desc_relation_protagonistes_ex'] = explication
                    elif question_number == 12:
                        result['type_relation_protagonistes'] = option_number
                        result['type_relation_protagonistes_ex'] = explication
                    elif question_number == 13:
                        result['escalade_violences'] = option_number
                        result['escalade_violences_ex'] = explication
                        # Update is_soustendent_violences if necessary
                        if option_number == 1:
                            is_soustendent_violences = True
                    elif question_number == 14:
                        result['statistiques'] = option_number
                        result['statistiques_ex'] = explication
                    elif question_number == 15:
                        result['autres_violences'] = option_number
                        result['autres_violences_ex'] = explication
                    elif question_number == 16:
                        result['citations'] = option_number
                        result['citations_ex'] = explication
                    elif question_number == 17:
                        result['ressources'] = option_number
                        result['ressources_ex'] = explication
                    elif question_number == 18:
                        result['consequences_auteur'] = option_number
                        result['consequences_auteur_ex'] = explication
                    elif question_number == 19:
                        result['consequences_victime'] = option_number
                        result['consequences_victime_ex'] = explication
        
                # Re-determine 'soustendent_violences' after ChatGPT processing
                if is_soustendent_violences:
                    result['soustendent_violences'] = 1
                elif is_in_vocabulaire_violence:
                    result['soustendent_violences'] = 0
                else:
                    result['soustendent_violences'] = -1

                # Create the explanation strings
                escalade_violences_bol = "Escalade_violences: " + ("Oui" if result['escalade_violences'] == 1 else "Non")
                culture_du_viol_bol = "Culture du viol: " + ("Oui" if result['culture_du_viol'] == 1 else "Non")
                sideration_bol = "Sideration: " + ("Oui" if result['sideration'] == 1 else "Non")
                vocabulaire_violence_bol = "Vocabulaire violence: " + ("Oui" if is_in_vocabulaire_violence else "Non")
                result['soustendent_violences_ex'] = ', '.join([escalade_violences_bol, culture_du_viol_bol, sideration_bol, vocabulaire_violence_bol])
    
                print(f"✅ Article {index+1} analyzed successfully!")
                logger.info(f"✅ Article {index+1} analyzed successfully!")
                final_status = "completed"
            else:
                result['classification_result'] = '-'
                print(f"❌ ChatGPT response is None for article {index + 1}")
                logger.warning(f"❌ ChatGPT response is None for article {index + 1}")
                final_status = "completed"
        else:
            result['classification_result'] = '-'
            print(f"⚠️  Article {index + 1} ({total_tokens} tokens) exceeds maximum token limit ({model_max_tokens} tokens)")
            logger.warning(f"⚠️ Article {index + 1} ({total_tokens} tokens) exceeds maximum token limit ({model_max_tokens} tokens)")
            big_article['count'] += 1
            final_status = "skipped" 
        
        # Final cancellation check
        if cancellation_event and cancellation_event.is_set():
            print(f"🛑 Article {index+1} processing cancelled at the end")
            logger.warning(f"🛑 Article {index+1} processing cancelled at the end")
            if progress_callback:
                progress_callback(index, "cancelled")
            return None

        # Call progress callback if provided
        if progress_callback:
            progress_callback(index, final_status)

        return result  # Return the result dictionary
        
    except Exception as e:
        # Check if this is due to cancellation
        if cancellation_event and cancellation_event.is_set():
            print(f"🛑 Article {index+1} processing cancelled due to exception")
            logger.warning(f"🛑 Article {index+1} processing cancelled due to exception")
            if progress_callback:
                progress_callback(index, "cancelled")
            return None
        
        print(f"❌ Error processing article {index + 1}: {e}")
        logger.error(f"❌ Error processing article {index + 1}: {e}")
        # Call progress callback if provided
        if progress_callback:
            progress_callback(index, "error")
            
        # In case of error, return result dictionary with default values
        result = {'index': index}
        # Define result_keys here for error case
        error_result_keys = [
            'agence', 'agence_ex', 'en_lien_avec_affaire', 'en_lien_avec_affaire_ex', 'mention_feminicide', 'mention_feminicide_ex', 
            'vocabulaire', 'vocs_violence_ex', 'vocs_minimisant_ex', 
            'sante_mentale', 'sante_mentale_ex', 'substance_psychotrope', 'substance_psychotrope_ex', 'animalisant', 'animalisant_ex', 
            'sideration', 'sideration_ex', 'desc_agresseur', 'desc_agresseur_ex', 
            'culture_du_viol', 'culture_du_viol_ex', 'validite', 'validite_ex', 'taille', 'taille_ex', 'classification_result',
            'soustendent_violences', 'soustendent_violences_ex',
            'type_violence', 'type_violence_ex', 'cadre_violence', 'cadre_violence_ex', 'feminicide', 'feminicide_ex',
            'sources', 'sources_ex', 'hierarchisation', 'hierarchisation_ex', 'desc_victime', 'desc_victime_ex',
            'nationalite_auteur', 'nationalite_auteur_ex', 'nationalite_victime', 'nationalite_victime_ex',
            'nationalite_suisse_auteur', 'nationalite_suisse_auteur_ex', 'nationalite_suisse_victime', 'nationalite_suisse_victime_ex',
            'desc_relation_protagonistes', 'desc_relation_protagonistes_ex', 'type_relation_protagonistes', 'type_relation_protagonistes_ex',
            'escalade_violences', 'escalade_violences_ex', 'statistiques', 'statistiques_ex', 'autres_violences', 'autres_violences_ex',
            'citations', 'citations_ex', 'ressources', 'ressources_ex', 'consequences_auteur', 'consequences_auteur_ex',
            'consequences_victime', 'consequences_victime_ex', 'motif_violence', 'motif_violence_ex'
        ]
        for key in error_result_keys:
            result[key] = '-'
        return result

# Updated main processing function with progress tracking
async def process_articles(df, corpora, config, progress_callback=None, cancellation_event=None):
    # Set OpenAI API key
    api_key = config.get('api_key')
    if not api_key:
        raise Exception("❌ No OpenAI API key found in config")
    
    set_openai_api_key(api_key)
    
    # Determine the maximum number of concurrent API calls
    max_concurrent_requests = 10  # Reduced for better stability
    semaphore = asyncio.Semaphore(max_concurrent_requests)

    tasks = []
    big_article = {'count': 0}

    print(f"🚀 Starting processing of {len(df)} articles...")
    logger.info(f"🚀 Starting processing of {len(df)} articles...")

    # Check for cancellation before starting
    if cancellation_event and cancellation_event.is_set():
        print("🛑 Processing cancelled before starting articles")
        logger.warning("🛑 Processing cancelled before starting articles")
        return df

    # Loop over each row in the DataFrame and create asynchronous tasks
    for index, row in df.iterrows():
        # Check for cancellation before creating each task
        if cancellation_event and cancellation_event.is_set():
            print(f"🛑 Processing cancelled before creating task for article {index+1}")
            logger.warning(f"🛑 Processing cancelled before creating task for article {index+1}")
            break

        task = process_article(index, row, corpora, config, big_article, semaphore, progress_callback, cancellation_event)
        tasks.append(task)

    # If no tasks were created due to cancellation, return original df
    if not tasks:
        print("🛑 No tasks created due to cancellation")
        logger.warning("🛑 No tasks created due to cancellation")
        return df
    
    # Await all tasks to process articles concurrently
    try:
        results = await asyncio.gather(*tasks, return_exceptions=True)
    except Exception as e:
        if cancellation_event and cancellation_event.is_set():
            print("🛑 Processing cancelled during asyncio.gather")
            logger.warning("🛑 Processing cancelled during asyncio.gather")
            return df
        raise e
        
    # Filter out None results (cancelled articles) and exceptions
    valid_results = []
    for result in results:
        if result is not None and not isinstance(result, Exception):
            valid_results.append(result)
        elif isinstance(result, Exception):
            print(f"❌ Exception in result: {result}")
            logger.error(f"❌ Exception in result: {result}")

    # Check if processing was cancelled
    if cancellation_event and cancellation_event.is_set():
        print("🛑 Processing was cancelled, returning partial results")
        logger.warning("🛑 Processing was cancelled, returning partial results")
        # We could still process the valid results we have so far
        if not valid_results:
            return df

    # Sort results by their index to maintain order
    valid_results.sort(key=lambda x: x['index'])

    print(f"📊 Processing complete. Adding {len(valid_results)} results to DataFrame...")
    logger.info(f"📊 Processing complete. Adding {len(valid_results)} results to DataFrame...")

    # If we have no valid results, return original DataFrame
    if not valid_results:
        print("⚠️  No valid results to add to DataFrame")
        logger.warning("⚠️ No valid results to add to DataFrame")
        return df


    # Add all the results to the DataFrame
    # Initialize result lists
    agence_results = []
    agence_ex = []
    en_lien_avec_affaire_results = []
    en_lien_avec_affaire_ex = []
    mention_feminicide_results = []
    mention_feminicide_ex = []
    vocabulaire_results = []
    vocs_violence_ex = []
    vocs_minimisant_ex = []
    sante_mentale_results = []
    sante_mentale_ex = []
    substance_psychotrope_results = []
    substance_psychotrope_ex = []
    animalisant_results = []
    animalisant_ex = []
    sideration_results = []
    sideration_ex = []
    culture_du_viol_results = []
    culture_du_viol_ex = []
    validite_results = []
    validite_ex = []
    taille_results = []
    taille_ex = []
    desc_agresseur_results = []
    desc_agresseur_ex = []

    classification_results = []
    soustendent_violences_results = []
    soustendent_violences_explications = []

    # ChatGPT-related results
    type_violence_results = []
    type_violence_explications = []
    cadre_violence_results = []
    cadre_violence_explications = []
    feminicide_results = []
    feminicide_explications = []
    sources_results = []
    sources_explications = []
    hierarchisation_results = []
    hierarchisation_explications = []
    desc_victime_results = []
    desc_victime_explications = []
    nationalite_auteur_results = []
    nationalite_auteur_explications = []
    nationalite_victime_results = []
    nationalite_victime_explications = []
    nationalite_suisse_auteur_results = []
    nationalite_suisse_auteur_explications = []
    nationalite_suisse_victime_results = []
    nationalite_suisse_victime_explications = []
    desc_relation_protagonistes_results = []
    desc_relation_protagonistes_explications = []
    type_relation_protagonistes_results = []
    type_relation_protagonistes_explications = []
    escalade_violences_results = []
    escalade_violences_explications = []
    statistiques_results = []
    statistiques_explications = []
    autres_violences_results = []
    autres_violences_explications = []
    citations_results = []
    citations_explications = []
    ressources_results = []
    ressources_explications = []
    consequences_auteur_results = []
    consequences_auteur_explications = []
    consequences_victime_results = []
    consequences_victime_explications = []

    # Create a mapping of processed indices to results for easier lookup
    results_by_index = {result['index']: result for result in valid_results}

    # Process all rows in original DataFrame order
    for index, row in df.iterrows():
        if index in results_by_index:
            result = results_by_index[index]
        else:
            # Create default result for cancelled/failed articles
            result = {'index': index}
            for key in ['agence', 'agence_ex', 'en_lien_avec_affaire', 'en_lien_avec_affaire_ex', 'mention_feminicide', 'mention_feminicide_ex', 
                       'vocabulaire', 'vocs_violence_ex', 'vocs_minimisant_ex', 
                       'sante_mentale', 'sante_mentale_ex', 'substance_psychotrope', 'substance_psychotrope_ex', 'animalisant', 'animalisant_ex', 
                       'sideration', 'sideration_ex', 'desc_agresseur', 'desc_agresseur_ex', 
                       'culture_du_viol', 'culture_du_viol_ex', 'validite', 'validite_ex', 'taille', 'taille_ex', 'classification_result',
                       'soustendent_violences', 'soustendent_violences_ex',
                       'type_violence', 'type_violence_ex', 'cadre_violence', 'cadre_violence_ex', 'feminicide', 'feminicide_ex',
                       'sources', 'sources_ex', 'hierarchisation', 'hierarchisation_ex', 'desc_victime', 'desc_victime_ex',
                       'nationalite_auteur', 'nationalite_auteur_ex', 'nationalite_victime', 'nationalite_victime_ex',
                       'nationalite_suisse_auteur', 'nationalite_suisse_auteur_ex', 'nationalite_suisse_victime', 'nationalite_suisse_victime_ex',
                       'desc_relation_protagonistes', 'desc_relation_protagonistes_ex', 'type_relation_protagonistes', 'type_relation_protagonistes_ex',
                       'escalade_violences', 'escalade_violences_ex', 'statistiques', 'statistiques_ex', 'autres_violences', 'autres_violences_ex',
                       'citations', 'citations_ex', 'ressources', 'ressources_ex', 'consequences_auteur', 'consequences_auteur_ex',
                       'consequences_victime', 'consequences_victime_ex', 'motif_violence', 'motif_violence_ex']:
                result[key] = '-'

        # Extract results from each row
        agence_results.append(result.get('agence', '-'))
        agence_ex.append(result.get('agence_ex', '-'))
        en_lien_avec_affaire_results.append(result.get('en_lien_avec_affaire', '-'))
        en_lien_avec_affaire_ex.append(result.get('en_lien_avec_affaire_ex', '-'))
        mention_feminicide_results.append(result.get('mention_feminicide', '-'))
        mention_feminicide_ex.append(result.get('mention_feminicide_ex', '-'))

        vocabulaire_results.append(result.get('vocabulaire', '-'))
        vocs_violence_ex.append(result.get('vocs_violence_ex', '-'))
        vocs_minimisant_ex.append(result.get('vocs_minimisant_ex', '-'))
        
        sante_mentale_results.append(result.get('sante_mentale', '-'))
        sante_mentale_ex.append(result.get('sante_mentale_ex', '-'))
        
        substance_psychotrope_results.append(result.get('substance_psychotrope', '-'))
        substance_psychotrope_ex.append(result.get('substance_psychotrope_ex', '-'))
        
        animalisant_results.append(result.get('animalisant', '-'))
        animalisant_ex.append(result.get('animalisant_ex', '-'))

        desc_agresseur_results.append(result.get('desc_agresseur', '-'))
        desc_agresseur_ex.append(result.get('desc_agresseur_ex', '-'))
        
        sideration_results.append(result.get('sideration', '-'))
        sideration_ex.append(result.get('sideration_ex', '-'))    
        
        culture_du_viol_results.append(result.get('culture_du_viol', '-'))
        culture_du_viol_ex.append(result.get('culture_du_viol_ex', '-'))

        validite_results.append(result.get('validite', '-'))
        validite_ex.append(result.get('validite_ex', '-'))
        
        taille_results.append(result.get('taille', '-'))
        taille_ex.append(result.get('taille_ex', '-'))
        classification_results.append(result.get('classification_result', '-'))
        soustendent_violences_results.append(result.get('soustendent_violences', '-'))
        soustendent_violences_explications.append(result.get('soustendent_violences_ex', '-'))

        # ChatGPT-related results
        type_violence_results.append(result.get('type_violence', '-'))
        type_violence_explications.append(result.get('type_violence_ex', '-'))
        cadre_violence_results.append(result.get('cadre_violence', '-'))
        cadre_violence_explications.append(result.get('cadre_violence_ex', '-'))
        feminicide_results.append(result.get('feminicide', '-'))
        feminicide_explications.append(result.get('feminicide_ex', '-'))
        sources_results.append(result.get('sources', '-'))
        sources_explications.append(result.get('sources_ex', '-'))
        hierarchisation_results.append(result.get('hierarchisation', '-'))
        hierarchisation_explications.append(result.get('hierarchisation_ex', '-'))
        desc_victime_results.append(result.get('desc_victime', '-'))
        desc_victime_explications.append(result.get('desc_victime_ex', '-'))
        nationalite_auteur_results.append(result.get('nationalite_auteur', '-'))
        nationalite_auteur_explications.append(result.get('nationalite_auteur_ex', '-'))
        nationalite_victime_results.append(result.get('nationalite_victime', '-'))
        nationalite_victime_explications.append(result.get('nationalite_victime_ex', '-'))
        nationalite_suisse_auteur_results.append(result.get('nationalite_suisse_auteur', '-'))
        nationalite_suisse_auteur_explications.append(result.get('nationalite_suisse_auteur_ex', '-'))
        nationalite_suisse_victime_results.append(result.get('nationalite_suisse_victime', '-'))
        nationalite_suisse_victime_explications.append(result.get('nationalite_suisse_victime_ex', '-'))
        desc_relation_protagonistes_results.append(result.get('desc_relation_protagonistes', '-'))
        desc_relation_protagonistes_explications.append(result.get('desc_relation_protagonistes_ex', '-'))
        type_relation_protagonistes_results.append(result.get('type_relation_protagonistes', '-'))
        type_relation_protagonistes_explications.append(result.get('type_relation_protagonistes_ex', '-'))
        escalade_violences_results.append(result.get('escalade_violences', '-'))
        escalade_violences_explications.append(result.get('escalade_violences_ex', '-'))
        statistiques_results.append(result.get('statistiques', '-'))
        statistiques_explications.append(result.get('statistiques_ex', '-'))
        autres_violences_results.append(result.get('autres_violences', '-'))
        autres_violences_explications.append(result.get('autres_violences_ex', '-'))
        citations_results.append(result.get('citations', '-'))
        citations_explications.append(result.get('citations_ex', '-'))
        ressources_results.append(result.get('ressources', '-'))
        ressources_explications.append(result.get('ressources_ex', '-'))
        consequences_auteur_results.append(result.get('consequences_auteur', '-'))
        consequences_auteur_explications.append(result.get('consequences_auteur_ex', '-'))
        consequences_victime_results.append(result.get('consequences_victime', '-'))
        consequences_victime_explications.append(result.get('consequences_victime_ex', '-'))

    # Add results to the DataFrame
    df["Article provient d'une agence"] = agence_results
    df["Explication - Article provient d'une agence"] = agence_ex
    df["Article en lien direct avec une affaire"] = en_lien_avec_affaire_results
    df["Explication - Article en lien direct avec une affaire"] = en_lien_avec_affaire_ex
    df["Taille de l'article"] = taille_results
    df["Explication - Taille de l'article"] = taille_ex
    df["Type de violence traitées"] = type_violence_results
    df["Explication - type de violence traitées"] = type_violence_explications
    df["Cadre de violence traitées"] = cadre_violence_results
    df["Explication - cadre de violence traitées"] = cadre_violence_explications
    df["Féminicide"] = feminicide_results
    df["Explication - Féminicide"] = feminicide_explications
    df["Le vocabulaire"] = vocabulaire_results
    df["Explication - Le vocabulaire violence"] = vocs_violence_ex
    df["Explication - Le vocabulaire minimisant"] = vocs_minimisant_ex
    df["Mention féminicide"] = mention_feminicide_results
    df["Explication - Mention féminicide"] = mention_feminicide_ex
    df["Les sources"] = sources_results
    df["Explication - Les sources"] = sources_explications
    df["La validité des informations "] = validite_results
    df["Explication - La validité des informations "] = validite_ex
    df["Hiérarchisation de l'information"] = hierarchisation_results
    df["Explication - hiérarchisation de l'information"] = hierarchisation_explications
    df["La description de la victime"] = desc_victime_results
    df["Explication - la description de la victime"] = desc_victime_explications
    df["La description de l'agresseur"] = desc_agresseur_results
    df["Explication - la description de l'agresseur"] = desc_agresseur_ex
    df["La nationalité de l'auteur est mentionnée"] = nationalite_auteur_results
    df["Explication - la nationalité de l'auteur est mentionnée"] = nationalite_auteur_explications
    df["La nationalité de la victime est mentionnée"] = nationalite_victime_results
    df["Explication - la nationalité de la victime est mentionnée"] = nationalite_victime_explications
    df["La nationalité suisse de l'auteur est mentionnée"] = nationalite_suisse_auteur_results
    df["Explication - la nationalité suisse de l'auteur est mentionnée"] = nationalite_suisse_auteur_explications
    df["La nationalité suisse de la victime est mentionnée"] = nationalite_suisse_victime_results
    df["Explication - la nationalité suisse de la victime est mentionnée"] = nationalite_suisse_victime_explications
    df["La santé mentale est mentionnée"] = sante_mentale_results
    df["Explication - La santé mentale est mentionnée"] = sante_mentale_ex
    df["Le rapport a des substances psychotropes est mentionné"] = substance_psychotrope_results
    df["Explication - Le rapport a des substances psychotropes est mentionné"] = substance_psychotrope_ex
    df["Une forme d'animalisation est présente"] = animalisant_results
    df["Explication - Une forme d'animalisation est présente"] = animalisant_ex
    df["La description de la relation entre les protagonistes"] = desc_relation_protagonistes_results
    df["Explication - la description de la relation entre les protagonistes"] = desc_relation_protagonistes_explications
    df["Le type de la relation entre les protagonistes"] = type_relation_protagonistes_results
    df["Explication - le type de la relation entre les protagonistes"] = type_relation_protagonistes_explications
    df["Les mécanismes qui sous-tendent les violences"] = soustendent_violences_results
    df["Explication - les mécanismes qui sous-tendent les violences"] = soustendent_violences_explications
    df["L'escalade /continuum  des violences est mentionnée"] = escalade_violences_results
    df["Explication - l'escalade /continuum  des violences est mentionnée"] = escalade_violences_explications
    df["Le processus de sidération est mentionnée"] = sideration_results
    df["Explication - Le processus de sidération est mentionnée"] = sideration_ex
    df["La culture du viol / objetisation /sexisme sont mentionnée"] = culture_du_viol_results
    df["Explication - La culture du viol / objetisation /sexisme sont mentionnée"] = culture_du_viol_ex
    df["Les statistiques"] = statistiques_results
    df["Explication - les statistiques"] = statistiques_explications
    df["La mention d'autres violences"] = autres_violences_results
    df["Explication - la mention d'autres violences"] = autres_violences_explications
    df["Citations"] = citations_results
    df["Explication - citations"] = citations_explications
    df["Ressources proposées"] = ressources_results
    df["Explication - ressources proposées"] = ressources_explications
    df["Conséquences des accusations sur l'auteur"] = consequences_auteur_results
    df["Explication - conséquences des accusations sur l'auteur"] = consequences_auteur_explications
    df["Conséquences des violences pour la victime"] = consequences_victime_results
    df["Explication - conséquences des violences pour la victime"] = consequences_victime_explications
    
    # Add all classification results to the DataFrame
    df["classification_result"] = classification_results

    # Save Results to CSV
    output_csv = config.get("csv_file_output")
    try:
        df.to_csv(output_csv, index=False, header=True, encoding='utf-8-sig')
        if cancellation_event and cancellation_event.is_set():
            print(f"⚠️  Partial results saved to: {output_csv} (processing was cancelled)")
            logger.warning(f"⚠️ Partial results saved to: {output_csv} (processing was cancelled)")
        else:
            print(f"✅ Results saved to: {output_csv}")
            logger.info(f"✅ Results saved to: {output_csv}")
    except Exception as e:
        print(f"❌ Error saving results: {e}")
        logger.error(f"❌ Error saving results: {e}")
        raise

    if cancellation_event and cancellation_event.is_set():
        print("⚠️  Processing was cancelled, partial results returned.")
        logger.warning("⚠️ Processing was cancelled, partial results returned.")
    else:
        print("✅ All articles analyzed and results saved.")
        logger.info("✅ All articles analyzed and results saved.")
    print(f"📊 {big_article['count']} articles exceeded token limits and were not processed by GPT.")
    logger.info(f"📊 {big_article['count']} articles exceeded token limits and were not processed by GPT.")

    return df