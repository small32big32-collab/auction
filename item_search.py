import json
from pathlib import Path


class ItemDatabase:

  def __init__(self, db_path: str = 'stalzone-database'):
    self.base_dir = Path(db_path) / 'ru' / 'items'
    self.items = {}  # {lower_name: {"id": ..., "name": ...}}
    self._index_items()

  def _index_items(self):
    if not self.base_dir.exists():
      print(f' Ошибка: Папка {self.base_dir} не найдена!')
      return

    for file_path in self.base_dir.rglob('*.json'):
      try:
        with open(file_path, 'r', encoding='utf-8') as f:
          data = json.load(f)
          item_id = data.get('id')
          lines = data.get('name', {}).get('lines', {})
          ru_name = lines.get('ru') or lines.get('en')

          if item_id and ru_name:
            self.items[ru_name.lower()] = {'id': item_id, 'name': ru_name}
      except Exception:
        continue

    print(f' Заиндексировано предметов из базы: {len(self.items)}')

  def search(self, query: str, limit: int = 5) -> list[dict]:
    """Ищет предметы по частичному совпадению названия."""
    query_clean = query.strip().lower()
    results = []

    for name_lower, item in self.items.items():
      if query_clean in name_lower:
        results.append(item)
        if len(results) >= limit:
          break

    return results


if __name__ == '__main__':
  db = ItemDatabase()

  # Тестовый поиск
  search_query = 'виток'
  found = db.search(search_query)

  print(f"\nРезультаты поиска по запросу '{search_query}':")
  for item in found:
    print(f"- {item['name']} (ID: {item['id']})")