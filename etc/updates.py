# -*- coding: utf-8 -*-
import logging
import os
import urllib
from datetime import datetime, timedelta
from dateutil import parser
from selenium.common.exceptions import NoSuchElementException

from api.InstagramAPI import InstagramAPI
from db_settings import db_session
from db_settings.model import UploadedData
from .constants import MAX_PHOTOS, USER, PASSWORD, FILES_DIR, ACCOUNTS

INSTAGRAM_URL = "https://www.instagram.com/"
PHOTO_XPATH = '//a[contains(@href, "taken-by={username}")]'
DESCRIPTION_BROTHER_XPATH = '//article/div/div/ul/li//span'


class Dowloader(object):
    def __init__(self, driver=None):
        self.driver = driver

    def find_links(self, username):
        self.driver.get(INSTAGRAM_URL + username)

        tags = self.driver.find_elements_by_xpath(
            PHOTO_XPATH.format(username=username)
        )
        return [i.get_attribute('href') for i in tags]

    def get_description(self, username):
        description = self.driver.find_element_by_xpath(
            DESCRIPTION_BROTHER_XPATH
        ).text
        return '\n'.join([description, f'@{username}'])

    def get_post_date(self):
        el = self.driver.find_element_by_tag_name('time')
        return parser.parse(el.get_attribute('datetime')).replace(tzinfo=None)

    def is_dublicate(self, url, description, is_video=False):
        now = datetime.utcnow()
        week_ago = now - timedelta(days=7)
        data = db_session.query(UploadedData.url, UploadedData.description) \
            .filter(UploadedData.creation_date > week_ago) \
            .filter(UploadedData.is_video == is_video) \
            .filter(UploadedData.creation_date <= now).all()

        for row in data:
            if row.url == url or row.description == description:
                return False
        return True

    def download(self):
        for username in ACCOUNTS:
            logging.info(f'Check links for {username}')
            links = self.find_links(username)

            for link in links:
                self.driver.get(link)
                date = self.get_post_date()

                if datetime.utcnow() - timedelta(
                        days=1) <= date <= datetime.utcnow():
                    try:
                        self.download_video(username)
                    except NoSuchElementException:
                        self.download_photo(username)

    def download_video(self, username):
        video = self.driver.find_element_by_tag_name('video')
        cover_photo = video.get_attribute('poster')
        video_url = video.get_attribute('src')
        description = self.get_description(username)
        if self.is_dublicate(video_url, description, is_video=True):
            UploadedData(
                    url=video_url, description=description, is_video=True,
                    cover_photo=cover_photo, is_uploaded=False)\
                .save()
            logging.info(f'Added new video link for {username}')

    def download_photo(self, username):
        img = self.driver.find_element_by_xpath('//img[@srcset]')
        url = img.get_attribute('srcset').split(',')[-1].split(' ')[0]
        description = self.get_description(username)
        if self.is_dublicate(url, description):
            UploadedData(
                    url=url, description=description,
                    is_uploaded=False)\
                .save()
            logging.info(f'Added new photo link for {username}')


class Uploder(object):
    def __init__(self):
        self.i_api = InstagramAPI(USER, PASSWORD)
        self.i_api.login()

        if not os.path.exists(FILES_DIR):
            os.mkdir(FILES_DIR)

    def upload(self):
        logging.info("Start uploading")
        data = db_session.query(UploadedData) \
            .filter(UploadedData.is_uploaded == False) \
            .limit(MAX_PHOTOS).all()

        if not data:
            logging.info('There are no data to upload')
            return

        for row in data:
            row.is_uploaded = True
            row.save()

            if row.is_video:
                self.upload_video(row.url, row.cover_photo, row.description)
            else:
                self.upload_photo(row.url, row.description)

        logging.info('Data are uploaded')

    def upload_video(self, video_url, cover_photo, description):
        video_local_path = os.path.join(FILES_DIR, video_url.split("/")[-1])
        cover_photo_path = os.path.join(
            FILES_DIR, cover_photo.split("/")[-1])

        urllib.request.urlretrieve(video_url, video_local_path)
        urllib.request.urlretrieve(cover_photo, cover_photo_path)

        self.i_api.upload_video(
            video_local_path, cover_photo_path, caption=description
        )
        os.unlink(video_local_path)
        os.unlink(cover_photo_path)

    def upload_photo(self, url, description):
        photo_path = os.path.join(FILES_DIR, url.split("/")[-1])
        urllib.request.urlretrieve(url, photo_path)
        self.i_api.upload_photo(photo_path, caption=description)
        os.unlink(photo_path)
