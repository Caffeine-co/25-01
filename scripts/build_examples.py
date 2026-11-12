"""可重复生成样例配置。所有示例参数是可调的游戏模型，不是医学数据。"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'examples'

def put(sub, name, obj):
    path = ROOT / sub / f'{name}.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

def drive(initial, rise, threshold, priority):
    return dict(initial=initial, rise_per_hour=rise, threshold=threshold, priority=priority)

artist = dict(
    id='human_artist', name='小林', biography='大学生，喜欢绘画，做事较谨慎。',
    traits=dict(extraversion=0.48, agreeableness=0.78, conscientiousness=0.75, openness=0.9),
    interests=dict(drawing=0.95), ambitions=dict(drawing=40),
    drives=dict(thirst=drive(30, 3.8, 45, 4), hunger=drive(20, 2.5, 50, 3),
                sleep_pressure=drive(25, 2.3, 65, 3), fatigue=drive(15, 1.1, 70, 2),
                creative_urge=drive(12, 0.8, 68, 0.9)),
    body=dict(initial_vitality=95, idle_recovery_per_hour=0.3, move_cost_per_hour=0.8,
              use_cost_per_hour=0.3, rest_recovery_per_hour=1.8,
              min_move_vitality=12, min_use_vitality=6,
              critical_drives=dict(thirst=[91, 1.8], hunger=[96, 0.8])))
reader = dict(
    id='human_reader', name='小周', biography='学生，外向、善于交际，喜欢阅读。',
    traits=dict(extraversion=0.8, agreeableness=0.58, conscientiousness=0.53, openness=0.65),
    interests=dict(reading=0.85), ambitions=dict(reading=40),
    drives=dict(thirst=drive(25, 3.7, 45, 4), hunger=drive(25, 2.4, 50, 3),
                sleep_pressure=drive(28, 2.5, 65, 3), fatigue=drive(12, 1.2, 70, 2)),
    body=artist['body'])
put('personas','artist',artist)
put('personas','reader',reader)
put('personas','caretaker', {**reader, 'id':'caretaker', 'name':'照护者',
                            'assist_amount': 22, 'assist_duration': 15, 'assist_threshold': 30})

world = dict(
    id='sustainable_apartment',
    locations=dict(bedroom={'hall':2}, hall={'bedroom':2,'kitchen':3,'studio':2},
                   kitchen={'hall':3}, studio={'hall':2}),
    resources=dict(water=dict(amount=18,capacity=40), food=dict(amount=10,capacity=30)),
    facilities=[
        dict(id='bed', location='bedroom', duration_minutes=240,
             effects=dict(sleep_pressure=-68, fatigue=-55), restorative=True),
        dict(id='tap', location='kitchen', duration_minutes=4,
             resource='water', units=1, effects=dict(thirst=-62)),
        dict(id='meal', location='kitchen', duration_minutes=25,
             resource='food', units=1, effects=dict(hunger=-66)),
        dict(id='practice_drawing', location='studio', duration_minutes=90,
             effects=dict(creative_urge=-38, fatigue=5), tags=['practice','skill:drawing']),
        dict(id='practice_reading', location='studio', duration_minutes=60,
             effects=dict(fatigue=2), tags=['practice','skill:reading'])],
    events=[dict(minute=1440,type='resource_add',resource='water',amount=12,repeat_every_minutes=1440),
            dict(minute=1440,type='resource_add',resource='food',amount=8,repeat_every_minutes=1440)]
)
put('worlds','apartment_sustainable',world)
put('worlds','apartment_scarce',{
    **world,'id':'scarce_apartment',
    'resources': dict(water=dict(amount=3,capacity=3),food=dict(amount=2,capacity=2)),
    'events':[dict(minute=300,type='facility_disable',facility='tap'),
              dict(minute=1300,type='facility_enable',facility='tap')]})
put('worlds','apartment_interrupt',{
    **world,'id':'interrupt_apartment',
    'events':world['events']+[dict(minute=550,type='vitality_change',actor='resident_01',amount=-95),
                              dict(minute=1200,type='vitality_change',actor='resident_01',amount=80)]})
put('worlds','apartment_messages',{
    **world,'id':'messages_apartment',
    'events':world['events']+[dict(minute=600,type='message',actor='resident_01',
                                    **{'from':'friend_01'}, text='下午一起去散步吗？', urgent=True)]})
put('scenarios','apartment_sustainable',dict(
    world='../worlds/apartment_sustainable.json',
    actors=[dict(id='resident_01',persona='../personas/artist.json',start_location='bedroom',
                 known_locations=list(world['locations']),
                 known_facilities=[f['id'] for f in world['facilities']],
                 commitments=[dict(minute=720,kind='practice',target='practice_drawing')],
                 skills=dict(drawing=4))]))
put('scenarios','apartment_scarce',dict(
    world='../worlds/apartment_scarce.json',
    actors=[dict(id='resident_01',persona='../personas/artist.json',start_location='bedroom',
                 known_locations=list(world['locations']),
                 known_facilities=[f['id'] for f in world['facilities']])]))
put('scenarios','apartment_interrupt',dict(
    world='../worlds/apartment_interrupt.json',
    actors=[dict(id='resident_01',persona='../personas/artist.json',start_location='bedroom',
                 known_locations=list(world['locations']),
                 known_facilities=[f['id'] for f in world['facilities']])]))
put('scenarios','apartment_messages',dict(
    world='../worlds/apartment_messages.json',
    actors=[dict(id='resident_01',persona='../personas/artist.json',start_location='bedroom',
                 known_locations=list(world['locations']),
                 known_facilities=[f['id'] for f in world['facilities']])]))
put('scenarios','roommates',dict(
    world='../worlds/apartment_sustainable.json', actors=[
        dict(id='resident_01',persona='../personas/artist.json',start_location='studio',
             known_locations=list(world['locations']),
             known_facilities=[f['id'] for f in world['facilities']],
             skills=dict(drawing=2)),
        dict(id='resident_02',persona='../personas/reader.json',start_location='studio',
             known_locations=list(world['locations']),
             known_facilities=[f['id'] for f in world['facilities']],
             skills=dict(reading=3)),
    ]))
print('Example scenarios generated.')
