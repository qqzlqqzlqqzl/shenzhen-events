"""Map explicit public aggregator category labels, never title/place keywords."""
import re

GROUPS = {
    '硬件创客': {'hardware / iot'},
    'AI与开源': {'artificial intelligence (ai)', 'machine learning (ml)', 'open source'},
    '产品与创业': {'product management', 'business analysis', 'cio'},
    '学习成长': {'tech leadership'},
    '软件开发': {'api', 'cloud', 'devops', 'java', 'javascript', 'docker / kubernetes',
                 'microsoft', 'testing / qa', 'rust', 'sap', 'cybersecurity / infosec',
                 'wordpress', 'software architecture', 'aws', 'azure', 'data / database',
                 'elixir', 'flutter', 'full-stack', 'python', 'mobile', 'php', 'game dev'},
}

def developer_category(description):
    # This is the source's exact public description format; arbitrary prose is not evidence.
    match = re.fullmatch(r'([^\n]{1,80}?) (?:conference|masterclass) (?:Online|in [^\n]{1,200})', str(description or '').strip())
    if not match:
        return '', []
    label = match[1].strip()
    topics = [topic for topic, labels in GROUPS.items() if label.casefold() in labels]
    return label, topics


def developer_event_type(description):
    # Preserve the public source's course/conference distinction.
    if re.fullmatch(r'[^\n]{1,80}? masterclass (?:Online|in [^\n]{1,200})', str(description or '').strip()):
        return 'CourseInstance'
    return 'ConferenceEvent'
