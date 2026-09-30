"""Extra audit K6: sanitize all session titles, literal wildcard searches."""
import pytest

from dashboard.hud import collectors, cost
from test_cost_views_contract import fixture_db


def test_title_redacted_consistently_before_truncation(fixture_db):
    con, home, now = fixture_db
    marker='EXAMPLE_ONLY_SECRET'
    title='Synthetic token='+marker+' suffix'
    con.execute('UPDATE sessions SET title=?, ended_at=NULL',(title,))
    con.execute('ALTER TABLE messages ADD COLUMN tool_name TEXT')
    con.execute('ALTER TABLE messages ADD COLUMN tool_calls TEXT')
    con.execute("UPDATE messages SET tool_name='synthetic'")
    con.commit()
    values=[collectors.collect_active_sessions()[0]['title'], collectors.collect_recent_sessions()[0]['title'],
            collectors.search_sessions(marker)[0]['title'], collectors.collect_session_detail('s')['title'],
            collectors.collect_tool_events()[0]['title'], cost._sanitize_title(title)]
    assert all(marker not in title and '[REDACTED]' in title for title in values)
    assert values[0]==values[1]==values[2]==values[3]==values[5]
    con.execute('UPDATE sessions SET title=?',('x'*110+' token='+marker,));con.commit()
    assert marker not in collectors.collect_session_detail('s')['title']
    assert len(collectors.collect_session_detail('s')['title'])<=120


@pytest.mark.parametrize('query,expected', [('%',['percent']),('_',['underscore']),('\\',['slash']),
    ('Synthetic',['s']),('absent',[])])
def test_search_special_characters_are_literal(fixture_db,query,expected):
    con,home,now=fixture_db
    con.executemany('INSERT INTO sessions(id,title,started_at) VALUES (?,?,?)',
        [('percent','100% done',now),('underscore','has_underscore',now),('slash','back\\slash',now)])
    con.commit()
    assert sorted(s['id'] for s in collectors.search_sessions(query))==expected
