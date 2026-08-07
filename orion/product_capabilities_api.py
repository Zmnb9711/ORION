from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/v1/capabilities", tags=["ORION capabilities"])


class CapabilitySection(BaseModel):
    id: str
    title: str
    description: str
    capabilities: list[str]


SECTIONS = [
    CapabilitySection(id="flight", title="Полет", description="Запуск и сопровождение полета.", capabilities=["Запуск выбранной миссии", "Определение самолета, карты и коалиции", "Контроль состояния самолета, топлива, двигателя и вооружения"]),
    CapabilitySection(id="atc", title="Virtual ATC", description="Диспетчерское сопровождение на русском и английском.", capabilities=["Запуск, руление и взлет", "Вход в зону, заход, посадка и уход на второй круг", "Аварийные процедуры и свободная форма запросов"]),
    CapabilitySection(id="awacs", title="AWACS", description="Воздушная обстановка и сопровождение целей.", capabilities=["BRAA, Picture, Bogey Dope и Declare", "Оценка воздушных угроз", "Сопровождение выбранной цели"]),
    CapabilitySection(id="mission-control", title="Mission Control", description="Интеллектуальное сопровождение задачи.", capabilities=["Анализ целей и угроз", "Рекомендации по маршруту, топливу и вооружению", "Контроль выполнения миссии"]),
    CapabilitySection(id="allies", title="Работа с союзниками", description="Запрос поддержки дружественных сил.", capabilities=["Лазерное целеуказание", "Дымовая маркировка", "Связь с JTAC, FAC, AWACS, танкером и дружественной авиацией"]),
    CapabilitySection(id="refueling", title="Дозаправка", description="Поиск и сопровождение воздушной дозаправки.", capabilities=["Поиск доступного танкера", "Позывной, частота и TACAN", "Положение, курс и расстояние до танкера"]),
    CapabilitySection(id="navigation", title="Навигация", description="Навигационная помощь во время полета.", capabilities=["Ближайший и запасные аэродромы", "Курс, расстояние, координаты и ETA", "Навигационные рекомендации"]),
    CapabilitySection(id="combat", title="Боевая помощь", description="Тактическая поддержка пилота.", capabilities=["Предупреждения о воздушных и наземных угрозах", "Рекомендации по атаке и отходу", "Оценка безопасного маршрута"]),
    CapabilitySection(id="debrief", title="Debrief", description="Послеполетный анализ.", capabilities=["Анализ выполнения задачи", "Разбор ошибок", "Рекомендации и журнал полета"]),
    CapabilitySection(id="communication", title="Общение", description="Рабочее и свободное голосовое взаимодействие.", capabilities=["Авиационный английский", "Авиационный русский", "Свободное общение и случайные разговоры"]),
    CapabilitySection(id="mission-pack", title="Mission Pack", description="Безопасная подготовка копии миссии для расширенных функций.", capabilities=["Создание копии и резервной копии", "Внедрение и проверка компонентов ORION", "Сохранение оригинальной миссии без изменений"]),
    CapabilitySection(id="console", title="Flight Console", description="Отдельное окно состояния ORION на мониторе.", capabilities=["Статусы подключений", "Последняя команда и сообщение", "Живые обновления и журнал событий"]),
    CapabilitySection(id="diagnostics", title="Диагностика", description="Проверка компонентов самого ORION.", capabilities=["Проверка Flight Bridge и Mission Pack", "Проверка микрофона и аудиовыхода", "Журнал ошибок и состояние AI"]),
]


@router.get("", response_model=list[CapabilitySection])
def list_capabilities() -> list[CapabilitySection]:
    return SECTIONS
