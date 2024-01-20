import datetime
import os
import random
from pathlib import Path
import requests
import tweepy
import boto3
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[0]


# todo make a Colorado Mushroom of the Day bot


def get_inat_observation() -> dict:
    base_url = "https://api.inaturalist.org/v1/observations"

    params = dict()
    taxa_include = [47169, 48250]
    taxa_exclude = [54743]
    params['taxon_id'] = ','.join([str(i) for i in taxa_include])
    params['without_taxon_id'] = ','.join([str(i) for i in taxa_exclude])

    params['rank'] = ['species', 'subspecies', 'variety']
    params['quality_grade'] = "research"
    params['photos'] = True
    params['photo_licensed'] = True
    params['licensed'] = True
    params['spam'] = False
    params['per_page'] = 200

    resp = requests.get(base_url, params=params)
    print(resp.url)
    print(resp.json()['total_results'])

    all_results_page = resp.json()['results']
    len_results = len(all_results_page)

    # filter out any observations already posted
    obs_already_posted = True
    while obs_already_posted:
        random_obs_index = random.randint(0, len_results - 1)
        selected_obs = all_results_page[random_obs_index]

        # if Item exists, the observation has already been posted
        ddb = query_ddb(obs_inat_uuid=selected_obs.get('uuid'))
        print('ddb:', ddb)
        obs_already_posted = ddb.get('Item')

    print(selected_obs)
    return selected_obs


def get_obs_attributes(obs_json: dict) -> dict:
    date_observed = obs_json.get('observed_on_details').get('date')

    obs_formatted = dict()
    obs_formatted['uuid'] = obs_json.get('uuid')
    obs_formatted['date_observed'] = date_observed
    obs_formatted['taxon_name'] = obs_json.get('taxon').get('name')
    obs_formatted['preferred_common_name'] = obs_json.get('taxon').get('preferred_common_name')
    obs_formatted['wikipedia_url'] = obs_json.get('taxon').get('wikipedia_url')
    obs_formatted['inat_uri'] = obs_json.get('uri')
    obs_formatted['place_guess'] = obs_json.get('place_guess')
    obs_formatted['photo_url'] = obs_json.get('photos')[0].get('url')  # todo post all photos, not just the first one
    obs_formatted['inat_username'] = obs_json.get('user').get('login')
    obs_formatted['inat_user_id'] = obs_json.get('user').get('id')
    obs_formatted['inat_user_uri'] = f"https://www.inaturalist.org/people/{obs_json.get('user').get('id')}"

    # obs_json['taxon']['name'] # "Ganoderma applanatum"
    # obs_json['taxon']['preferred_common_name'] # "artist's bracket"
    # obs_json['taxon']['wikipedia_url'] # "http://en.wikipedia.org/wiki/Ganoderma_applanatum"
    #
    # obs_json['uri'] # "https://www.inaturalist.org/observations/197078978"
    # obs_json['place_guess'] # "Columbia County, NY, USA"
    #
    # # 1st photo
    # obs_json['photos'][0]['url'] # "https://inaturalist-open-data.s3.amazonaws.com/photos/347017735/square.jpg"
    #
    # # User name
    # obs_json['user']['name'] # "Josie Laing"
    # # User ID
    # obs_json['user']['id'] # 3581001

    return obs_formatted


def format_tweet_text(obs_formatted: dict):
    if not obs_formatted['preferred_common_name']:
        common_name = ''
    else:
        common_name = f" ({obs_formatted['preferred_common_name']})"

    tweet = f"""Today's Mushroom of the Day is this {obs_formatted['taxon_name']}{common_name}, observed by iNat user @/{obs_formatted['inat_username']} on {obs_formatted['date_observed']} in {obs_formatted['place_guess']}. See the full observation here: {obs_formatted['inat_uri']}"""
    return tweet


def post_observation_twitter(tweepy_client, tweet_text: str):
    tweet_resp = tweepy_client.create_tweet(
        text=tweet_text,
    )
    return tweet_resp


def query_ddb(obs_inat_uuid: str):
    ddb_tablename = "shrooms-everyday-tweeted-observations"

    client = boto3.client('dynamodb')
    items = client.get_item(
        TableName=ddb_tablename,
        Key={'inat_uuid': {'S': str(obs_inat_uuid)}}
    )
    return items


def add_observation_id_to_ddb(obs_inat_uuid: str, tweet_id: str):
    ddb_tablename = "shrooms-everyday-tweeted-observations"

    client = boto3.client('dynamodb')
    client.put_item(
        TableName=ddb_tablename,
        Item={
            'inat_uuid': {'S': str(obs_inat_uuid)},
            'timestamp': {'S': str(datetime.datetime.utcnow())},
            'tweet_id': {'S': str(tweet_id)},
        }
    )


def lambda_handler(event, context):
    load_dotenv()

    print("Authenticating")
    consumer_key = os.getenv("CONSUMER_KEY")
    consumer_secret = os.getenv("CONSUMER_SECRET")
    access_token = os.getenv("ACCESS_TOKEN")
    access_token_secret = os.getenv("ACCESS_TOKEN_SECRET")
    bearer_token = os.getenv("BEARER_TOKEN")

    client = tweepy.Client(bearer_token=bearer_token,
                           consumer_key=consumer_key,
                           consumer_secret=consumer_secret,
                           access_token=access_token,
                           access_token_secret=access_token_secret)

    print("Getting iNaturalist observation")
    inat_obs = get_inat_observation()
    inat_obs_formatted = get_obs_attributes(inat_obs)
    inat_obs_uuid = inat_obs_formatted.get('uuid')

    tweet_text = format_tweet_text(obs_formatted=inat_obs_formatted)
    print(tweet_text)

    print("Posting tweet")
    try:
        resp = post_observation_twitter(
            tweepy_client=client,
            tweet_text=tweet_text,
        )
        print('tweet response:', resp)
        # tweepy_client.create_tweet() returns a named tuple
        tweet_id = resp.data.get('id')

        # add observation & tweet detail to dynamodb
        add_observation_id_to_ddb(obs_inat_uuid=inat_obs_uuid, tweet_id=tweet_id)
    except Exception as e:
        raise e

    return {"statusCode": 200, "tweet": resp}
