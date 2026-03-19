import datetime as dt
import numpy as np

filename = 'c:/users/buran/Downloads/gerbil colony weights.xlsx'

def process_sheet(df):
    results = []
    for _, row in df.dropna(subset=['Date']).iterrows():
        if row['Date'] == 'C':
            continue
        date = row['Date'].date()
        if date > dt.date.today():
            continue
        weight = row['Weight']
        feed_20 = row['20mg']
        feed_500 = row['500mg']
        total = row['Total (g)']
        notes = row['Notes']
        baseline = ('baseline' in str(row['Notes']).lower())
        if np.isnan(feed_20):
            feed_20 = 0
        if np.isnan(feed_500):
            feed_500 = 0
        if isinstance(total, str):
            if total == 'FF':
                if isinstance(notes, str):
                    if notes.lower() == 'baseline':
                        notes = 'free feed'
                    else:
                        notes = f'free feed, {notes}'
                else:
                    notes = 'free feed'
            total = 0
        if np.isnan(total):
            total = 0
        if (feed_20 == 0) and (feed_500) == 0:
            if total != 0:
                feed_500 = total / 0.5
        calc_total = ((0.5 * feed_500) + (0.02 * feed_20))
        if abs(total-calc_total) > 0.1:
            if total != 0:
                print(calc_total, total, feed_500, feed_20)

        if np.isnan(weight):
            weight = None
        if not isinstance(notes, str):
            notes = None
        result = {
            'date': date,
            'weight': weight,
            'feed': {'20mg': feed_20, '500mg': feed_500},
            'baseline': baseline,
            'notes': notes,
        }
        results.append(result)
    return results


from app import create_app, db
from app import models
import pandas as pd

def upload_weight_logs():
    app = create_app()
    with app.app_context():
        feed_20 = models.Feed.query.filter_by(name='20mg').first()
        feed_500 = models.Feed.query.filter_by(name='500mg').first()
        sheets = pd.read_excel(filename, sheet_name=None, skiprows=4)

        for wl in models.WeightLog.query.all():
            db.session.delete(wl)
        for fl in models.FeedLog.query.all():
            db.session.delete(fl)
        db.session.commit()

        for animal_id, sheet in sheets.items():
            animal_id = animal_id.replace(' #', '-')
            animal = models.Animal.query.filter_by(custom_id=animal_id).first()
            print(animal_id, animal)
            for row in process_sheet(sheet):
                #if row['notes'] is None and row['weight'] is None and row['feed']['20mg'] == 0 and row['feed']['500mg'] == 0:
                #    continue
                wl = models.WeightLog(
                    animal_id=animal.id,
                    date=row['date'],
                    weight=row['weight'],
                    notes=row['notes'],
                    baseline=row['baseline'],
                )
                db.session.add(wl)
                db.session.add(models.FeedLog(
                    animal_id=animal.id,
                    feed_id=feed_20.id,
                    date=row['date'],
                    quantity=row['feed']['20mg'],
                ))
                db.session.add(models.FeedLog(
                    animal_id=animal.id,
                    feed_id=feed_500.id,
                    date=row['date'],
                    quantity=row['feed']['500mg'],
                ))
        db.session.commit()


def fix_animal_id():
    app = create_app()
    with app.app_context():
        feed_20 = models.Feed.query.filter_by(name='20mg').first()
        feed_500 = models.Feed.query.filter_by(name='500mg').first()
        sheets = pd.read_excel(filename, sheet_name=None, skiprows=4)

        for wl in models.WeightLog.query.all():
            db.session.delete(wl)
        for fl in models.FeedLog.query.all():
            db.session.delete(fl)
        db.session.commit()

        for animal_id, sheet in sheets.items():
            animal_id = animal_id.replace(' #', '-')
            animal = models.Animal.query.filter_by(custom_id=animal_id).first()
            print(animal_id, animal)
            for row in process_sheet(sheet):
                #if row['notes'] is None and row['weight'] is None and row['feed']['20mg'] == 0 and row['feed']['500mg'] == 0:
                #    continue
                wl = models.WeightLog(
                    animal_id=animal.id,
                    date=row['date'],
                    weight=row['weight'],
                    notes=row['notes'],
                    baseline=row['baseline'],
                )
                db.session.add(wl)
                db.session.add(models.FeedLog(
                    animal_id=animal.id,
                    feed_id=feed_20.id,
                    date=row['date'],
                    quantity=row['feed']['20mg'],
                ))
                db.session.add(models.FeedLog(
                    animal_id=animal.id,
                    feed_id=feed_500.id,
                    date=row['date'],
                    quantity=row['feed']['500mg'],
                ))
        db.session.commit()
