"""
Программа для резервного копирования фотографий VK на Яндекс.Диск.

Автор: Березина Анастасия
"""

import json
import logging
import os
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import requests
from tqdm import tqdm

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass 


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


class VKPhotoBackup:
    """Класс для резервного копирования фотографий VK на Яндекс.Диск."""
    
    VK_API_VERSION = '5.131'
    VK_API_BASE_URL = 'https://api.vk.com/method'
    YANDEX_API_BASE_URL = 'https://cloud-api.yandex.net/v1/disk'
    
    def __init__(self, vk_token: str, yandex_token: str):
        """
        Инициализация класса.
        
        Args:
            vk_token: Токен доступа к VK API
            yandex_token: Токен доступа к Яндекс.Диск API
        """
        self.vk_token = vk_token
        self.yandex_token = yandex_token
        self.session = requests.Session()
        
        self.session.headers.update({
            'Authorization': f'OAuth {yandex_token}',
            'Content-Type': 'application/json'
        })
    
    def check_yandex_disk_availability(self) -> bool:
        """
        Проверка доступности Яндекс.Диска и валидности токена.
        
        Returns:
            True если Яндекс.Диск доступен
            
        Raises:
            requests.RequestException: Ошибка при подключении к Яндекс.Диску
            ValueError: Невалидный токен
        """
        logger.info("Проверяем доступность Яндекс.Диска...")
        
        try:
            response = self.session.get(
                f'{self.YANDEX_API_BASE_URL}/resources',
                params={'path': '/'},
                timeout=30
            )
            
            if response.status_code == 401:
                raise ValueError("Невалидный токен Яндекс.Диска")
            elif response.status_code == 200:
                logger.info(" Яндекс.Диск доступен")
                return True
            else:
                response.raise_for_status()
                
        except requests.RequestException as e:
            logger.error(f"Ошибка при подключении к Яндекс.Диску: {e}")
            raise
    
    def check_vk_token_validity(self) -> bool:
        """
        Проверка валидности VK токена.
        
        Returns:
            True если токен валидный
            
        Raises:
            requests.RequestException: Ошибка при подключении к VK API
            ValueError: Невалидный токен
        """
        logger.info("Проверяем валидность VK токена...")
        
        params = {
            'access_token': self.vk_token,
            'v': self.VK_API_VERSION
        }
        
        try:
            response = requests.get(
                f'{self.VK_API_BASE_URL}/account.getProfileInfo',
                params=params,
                timeout=30
            )
            response.raise_for_status()
            
            data = response.json()
            
            if 'error' in data:
                error_code = data['error'].get('error_code', 0)
                if error_code == 5:  # User authorization failed
                    raise ValueError("Невалидный токен VK")
                else:
                    raise ValueError(f"VK API Error: {data['error'].get('error_msg', 'Неизвестная ошибка')}")
            
            logger.info("VK токен валидный")
            return True
            
        except requests.RequestException as e:
            logger.error(f"Ошибка при подключении к VK API: {e}")
            raise
    
    def check_folder_exists(self, folder_name: str) -> bool:
        """
        Проверка существования папки на Яндекс.Диске.
        
        Args:
            folder_name: Имя папки для проверки
            
        Returns:
            True если папка существует
        """
        try:
            response = self.session.get(
                f'{self.YANDEX_API_BASE_URL}/resources',
                params={'path': f'/{folder_name}'},
                timeout=30
            )
            
            return response.status_code == 200
            
        except requests.RequestException:
            return False
    
    def get_profile_photos(self, user_id: str, count: int = 5) -> List[Dict]:
        """
        Получение фотографий профиля пользователя VK.
        
        Args:
            user_id: ID пользователя VK
            count: Количество фотографий для получения
            
        Returns:
            Список словарей с данными фотографий
            
        Raises:
            requests.RequestException: Ошибка при запросе к VK API
            ValueError: Ошибка в ответе VK API
        """
        logger.info(f"Получаем фотографии профиля пользователя {user_id}")
        
        params = {
            'owner_id': user_id,
            'album_id': 'profile',
            'extended': 1,
            'photo_sizes': 1,
            'count': count,
            'access_token': self.vk_token,
            'v': self.VK_API_VERSION
        }
        
        try:
            response = requests.get(
                f'{self.VK_API_BASE_URL}/photos.get',
                params=params,
                timeout=30
            )
            response.raise_for_status()
            
            data = response.json()
            
            if 'error' in data:
                error_msg = data['error'].get('error_msg', 'Неизвестная ошибка')
                raise ValueError(f"VK API Error: {error_msg}")
            
            photos = data.get('response', {}).get('items', [])
            logger.info(f"Найдено {len(photos)} фотографий")
            
            return photos
            
        except requests.RequestException as e:
            logger.error(f"Ошибка при запросе к VK API: {e}")
            raise
        except (KeyError, ValueError) as e:
            logger.error(f"Ошибка в ответе VK API: {e}")
            raise
    
    def get_largest_photo_size(self, photo: Dict) -> Tuple[str, str]:
        """
        Получение фотографии максимального размера.
        
        Args:
            photo: Словарь с данными фотографии
            
        Returns:
            Кортеж (URL фотографии, тип размера)
        """
        sizes = photo.get('sizes', [])
        if not sizes:
            raise ValueError("Размеры фотографии не найдены")
        
        # Находим фотографию с максимальным разрешением
        max_size = 0
        best_photo = sizes[0]
        
        for size in sizes:
            total_pixels = size.get('width', 0) * size.get('height', 0)
            if total_pixels > max_size:
                max_size = total_pixels
                best_photo = size
        
        return best_photo['url'], best_photo['type']
    
    def generate_filename(self, photo: Dict, photos: List[Dict], used_filenames: set) -> str:
        """
        Генерация уникального имени файла на основе количества лайков.
        
        Args:
            photo: Данные фотографии
            photos: Список всех фотографий (для проверки дубликатов)
            used_filenames: Множество уже использованных имён файлов
            
        Returns:
            Уникальное имя файла
        """
        likes_count = photo.get('likes', {}).get('count', 0)
        photo_id = photo.get('id', 0)
        
        # Проверяем, есть ли другие фотографии с таким же количеством лайков
        same_likes_photos = [
            p for p in photos 
            if p.get('likes', {}).get('count', 0) == likes_count
        ]
        
        # Базовое имя файла
        if len(same_likes_photos) > 1:
            # Добавляем дату, если есть дубликаты по лайкам
            photo_date = datetime.fromtimestamp(photo.get('date', 0))
            date_str = photo_date.strftime('%Y-%m-%d')
            base_filename = f"{likes_count}_{date_str}"
        else:
            base_filename = f"{likes_count}"
        
        filename = f"{base_filename}.jpg"
        counter = 1
        
        while filename in used_filenames:
            if counter == 1:
                filename = f"{base_filename}_{photo_id}.jpg"
            else:
                filename = f"{base_filename}_{photo_id}_{counter}.jpg"
            counter += 1
        
        used_filenames.add(filename)
        return filename
    
    def create_yandex_folder(self, folder_name: str) -> bool:
        """
        Создание папки на Яндекс.Диске с проверкой существования.
        
        Args:
            folder_name: Имя папки
            
        Returns:
            True если папка создана или уже существует
            
        Raises:
            requests.RequestException: Ошибка при создании папки
        """
        logger.info(f"Проверяем существование папки '{folder_name}' на Яндекс.Диске")
        
        if self.check_folder_exists(folder_name):
            logger.info("Папка уже существует")
            return True
        
        logger.info(f"Создаём новую папку '{folder_name}' на Яндекс.Диске")
        
        try:
            response = self.session.put(
                f'{self.YANDEX_API_BASE_URL}/resources',
                params={'path': f'/{folder_name}'},
                timeout=30
            )
            
            if response.status_code == 201:
                logger.info("Папка успешно создана")
                return True
            elif response.status_code == 409:
                logger.info("Папка уже существует (создалась параллельно)")
                return True
            else:
                response.raise_for_status()
                
        except requests.RequestException as e:
            logger.error(f"Ошибка при создании папки: {e}")
            raise
    
    def upload_photo_to_yandex(
        self, 
        photo_url: str, 
        filename: str, 
        folder_name: str
    ) -> bool:
        """
        Загрузка фотографии на Яндекс.Диск по URL.
        
        Args:
            photo_url: URL фотографии
            filename: Имя файла для сохранения
            folder_name: Имя папки на Яндекс.Диске
            
        Returns:
            True если загрузка успешна
            
        Raises:
            requests.RequestException: Ошибка при загрузке
        """
        try:
            params = {
                'path': f'/{folder_name}/{filename}',
                'url': photo_url
            }
            
            response = self.session.post(
                f'{self.YANDEX_API_BASE_URL}/resources/upload',
                params=params,
                timeout=60
            )
            
            if response.status_code == 202:
                return True
            else:
                response.raise_for_status()
                
        except requests.RequestException as e:
            logger.error(f"Ошибка при загрузке {filename}: {e}")
            raise
    
    def save_photos_info(self, photos_info: List[Dict], user_id: str) -> str:
        """
        Сохранение информации о фотографиях в JSON файл.
        
        Args:
            photos_info: Список с информацией о фотографиях
            user_id: ID пользователя
            
        Returns:
            Имя созданного файла
        """
        filename = f"photos_info_{user_id}.json"
        
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(photos_info, f, ensure_ascii=False, indent=2)
            
            logger.info(f"Информация о фотографиях сохранена в {filename}")
            return filename
            
        except IOError as e:
            logger.error(f"Ошибка при сохранении JSON файла: {e}")
            raise
    
    def backup_photos(self, user_id: str, count: int = 5) -> Dict:
        """
        Основная функция резервного копирования фотографий.
        
        Args:
            user_id: ID пользователя VK
            count: Количество фотографий для копирования
            
        Returns:
            Словарь с результатами операции
            
        Raises:
            Exception: Различные ошибки в процессе выполнения
        """
        logger.info("=" * 50)
        logger.info("НАЧИНАЕМ РЕЗЕРВНОЕ КОПИРОВАНИЕ ФОТОГРАФИЙ VK")
        logger.info("=" * 50)
        
        try:
            logger.info("Выполняем предварительные проверки...")
            self.check_vk_token_validity()
            self.check_yandex_disk_availability()
            
            photos = self.get_profile_photos(user_id, count)
            
            if not photos:
                logger.warning("У пользователя нет фотографий в профиле")
                return {
                    'success': False, 
                    'message': 'У пользователя нет фотографий в профиле или профиль закрыт'
                }
            
            def get_max_size(photo):
                sizes = photo.get('sizes', [])
                if not sizes:
                    return 0
                return max(s.get('width', 0) * s.get('height', 0) for s in sizes)
            
            photos.sort(key=get_max_size, reverse=True)
            
            folder_name = f"VK_Photos_{user_id}_{datetime.now().strftime('%Y-%m-%d')}"
            self.create_yandex_folder(folder_name)
            
            photos_info = []
            successful_uploads = 0
            used_filenames = set()  # set для отслеживания уникальности имён файлов
            
            logger.info(f"Загружаем {len(photos)} фотографий...")
            
            with tqdm(total=len(photos), desc="Загрузка фото", unit="фото") as pbar:
                for i, photo in enumerate(photos):
                    try:
                        photo_url, size_type = self.get_largest_photo_size(photo)
                        
                        filename = self.generate_filename(photo, photos, used_filenames)
                        
                        self.upload_photo_to_yandex(photo_url, filename, folder_name)
                        
                        photos_info.append({
                            'file_name': filename,
                            'size': size_type
                        })
                        
                        successful_uploads += 1
                        pbar.set_postfix({
                            'Успешно': successful_uploads,
                            'Текущий': filename
                        })
                        
                        time.sleep(0.5)
                        
                    except Exception as e:
                        logger.error(f"Ошибка при обработке фотографии {i+1}: {e}")
                    
                    finally:
                        pbar.update(1)
            
            if successful_uploads == 0:
                logger.error("Ни одна фотография не была загружена")
                return {
                    'success': False,
                    'message': 'Ни одна фотография не была загружена. Проверьте доступность сервисов.'
                }
            
            json_filename = self.save_photos_info(photos_info, user_id)
            
            result = {
                'success': True,
                'total_photos': len(photos),
                'uploaded_photos': successful_uploads,
                'folder_name': folder_name,
                'json_file': json_filename,
                'photos_info': photos_info
            }
            
            logger.info("=" * 50)
            logger.info("РЕЗЕРВНОЕ КОПИРОВАНИЕ ЗАВЕРШЕНО")
            logger.info(f"Папка на Яндекс.Диске: {folder_name}")
            logger.info(f"JSON файл: {json_filename}")
            logger.info(f"Загружено: {successful_uploads}/{len(photos)} фотографий")
            logger.info("=" * 50)
            
            return result
            
        except ValueError as e:
            logger.error(f"Ошибка валидации: {e}")
            return {
                'success': False,
                'message': str(e)
            }
        except Exception as e:
            logger.error(f"Критическая ошибка: {e}")
            return {
                'success': False,
                'message': str(e)
            }


def validate_and_clean_user_id(user_id: str) -> str:
    """
    Валидация и очистка ID пользователя VK.
    
    Args:
        user_id: ID пользователя (может содержать префикс 'id' или '@')
        
    Returns:
        Очищенный числовой ID
        
    Raises:
        ValueError: Если ID некорректный
    """
    user_id = user_id.strip()
    
    if user_id.startswith('https://vk.com/'):
        user_id = user_id.replace('https://vk.com/', '')
    
    if user_id.startswith('id'):
        user_id = user_id[2:]  
    elif user_id.startswith('@'):
        user_id = user_id[1:]  
    
    if not user_id.isdigit():
        raise ValueError(
            f"Некорректный ID пользователя: '{user_id}'\n"
            f"ID должен содержать только цифры или быть в формате 'id123456'\n"
            f"Примеры правильного ввода: 53688675, id53688675, @id53688675"
        )
    
    return user_id


def get_user_input() -> Tuple[str, int]:
    """
    Получение входных данных от пользователя.
    
    Returns:
        Кортеж (user_id, count)
    """
    print("=" * 50)
    print("РЕЗЕРВНОЕ КОПИРОВАНИЕ ФОТОГРАФИЙ VK")
    print("=" * 50)
    print("Примеры ввода ID: 53688675, id53688675, @id53688675")
    print("   или скопируйте ссылку: https://vk.com/id53688675")
    print()
    
    while True:
        user_input = input("Введите ID пользователя VK: ").strip()
        if not user_input:
            print("ID пользователя не может быть пустым!")
            continue
            
        try:
            user_id = validate_and_clean_user_id(user_input)
            print(f"Обрабатываем пользователя с ID: {user_id}")
            break
        except ValueError as e:
            print(f"{e}")
            continue
    
    while True:
        count_input = input("Количество фотографий (по умолчанию 5): ").strip()
        
        if not count_input:
            count = 5
            break
        
        try:
            count = int(count_input)
            if count > 0:
                break
            else:
                print("Количество должно быть больше 0!")
        except ValueError:
            print("Введите корректное число!")
    
    return user_id, count


def get_tokens_from_env() -> Tuple[str, str]:
    """
    Получение токенов из переменных окружения.
    
    Returns:
        Кортеж (vk_token, yandex_token)
        
    Raises:
        ValueError: Если токены не найдены в переменных окружения
    """
    vk_token = os.getenv('VK_TOKEN')
    yandex_token = os.getenv('YANDEX_TOKEN')
    
    if not vk_token:
        raise ValueError(
            "VK_TOKEN не найден в переменных окружения!\n"
            "Установите переменную: export VK_TOKEN='ваш_токен'\n"
            "Или создайте файл .env с токенами"
        )
    
    if not yandex_token:
        raise ValueError(
            "YANDEX_TOKEN не найден в переменных окружения!\n"
            "Установите переменную: export YANDEX_TOKEN='ваш_токен'\n"
            "Или создайте файл .env с токенами"
        )
    
    return vk_token, yandex_token


def main():
    """Основная функция программы."""
    try:
        vk_token, yandex_token = get_tokens_from_env()
        
        user_id, count = get_user_input()
        
        backup = VKPhotoBackup(vk_token, yandex_token)
        result = backup.backup_photos(user_id, count)
        
        if result['success']:
            print(f"\nРезервное копирование успешно завершено!")
            print(f"Папка: {result['folder_name']}")
            print(f"JSON: {result['json_file']}")
            print(f"Загружено: {result['uploaded_photos']} фотографий")
            
            if result['uploaded_photos'] < result['total_photos']:
                failed_count = result['total_photos'] - result['uploaded_photos']
                print(f" Внимание: {failed_count} фотографий не удалось загрузить")
        else:
            print(f"\n Ошибка: {result['message']}")
            sys.exit(1)
            
    except ValueError as e:
        print(f"\n Ошибка конфигурации: {e}")
        print("\n Инструкция по настройке:")
        print("1. Создайте файл .env в папке с программой")
        print("2. Добавьте в него строки:")
        print("   VK_TOKEN=ваш_vk_токен")
        print("   YANDEX_TOKEN=ваш_яндекс_токен")
        print("3. Запустите программу снова")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\nОперация прервана пользователем")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Неожиданная ошибка: {e}")
        print(f"\nПроизошла неожиданная ошибка: {e}")
        print("Пожалуйста, проверьте:")
        print("• Подключение к интернету")
        print("• Правильность токенов")
        print("• Доступность VK и Яндекс.Диск")
        sys.exit(1)


if __name__ == '__main__':
    main()