"""
Automated test suite for the World of Warcraft Item and Item Set API. Uses the `py.test` package as a test runner.
Also uses the `requests` package to make HTTP requests to the Battle.net servers.

Usage: `python test_item_api.py`
"""
import json
import pytest
import requests
from requests.exceptions import HTTPError

DEFAULT_REGION = 'us.battle.net'
ITEM_API_ENDPOINT = 'http://{region}/api/wow/item/{object_id}'
ITEM_SET_API_ENDPOINT = 'http://{region}/api/wow/item/set/{object_id}'


def pytest_generate_tests(metafunc):
    """ Generate additional test cases for test functions with both the `region` and `locale` parameters present in
    order to allow testing of all possible regions and locale combinations. This allows any failures that occur for
    a particular region/locale combination to be reported as a separate test failure. """
    if 'region' in metafunc.fixturenames and 'locale' in metafunc.fixturenames:
        with open('regions.json', 'r') as regions_file:
            regions_data = json.load(regions_file)
        region_locale_combinations = []
        for region_name, locales in regions_data.items():
            region_locale_combinations.extend([region_name, locale] for locale in locales)
        metafunc.parametrize('region,locale', region_locale_combinations)


class TestItemAPI(object):

    def test_individual_item(self):
        """ Test the expected case for an individual item. """
        thunderfury_item_id = 19019
        response = self.call_api(ITEM_API_ENDPOINT, object_id=thunderfury_item_id)
        self.assert_success(response)

        data = response.json()
        assert data['id'] == thunderfury_item_id, 'item ID in response did not match request'
        assert 'Thunderfury' in data['name']

    @pytest.mark.parametrize('invalid_item_id', ['', -1, 'magical crawdad'])
    def test_invalid_parameter(self, invalid_item_id):
        """ Ensure that requests using an invalid item ID return a 404 error. """
        with pytest.raises(HTTPError) as e:
            self.call_api(ITEM_API_ENDPOINT, object_id=invalid_item_id)
        self.assert_failure(e.value.response, error_code=404)

    def test_invalid_endpoint(self):
        """ Ensure that requests to an non-existent route return a 404 error. """
        response = requests.get('http://{region}/api/wow/fake_api_endpoint'.format(region=DEFAULT_REGION))
        self.assert_failure(response, error_code=404)

    def test_invalid_method(self):
        """ Ensure that requests using unsupported HTTP methods return a 500 error. """
        # You can't just delete Sulfuras, Hand of Ragnaros...
        response = requests.delete(ITEM_API_ENDPOINT.format(region=DEFAULT_REGION, object_id=17182))
        self.assert_failure(response, error_code=500)

        response = requests.put(ITEM_API_ENDPOINT.format(region=DEFAULT_REGION, object_id=17182))
        self.assert_failure(response, error_code=500)

    def test_localization(self, region, locale):
        """ Ensure that requests to a given region return a response with a supported locale. """
        teebu_blazing_longsword_id = 1728
        response = self.call_api(
            region=region,
            endpoint=ITEM_API_ENDPOINT,
            object_id=teebu_blazing_longsword_id,
            locale=locale
        )
        self.assert_success(response)

        assert 'content-language' in response.headers, 'response headers missing content-language'
        response_locale = response.headers['content-language'].replace('-', '_', 1)
        assert response_locale in self.regions_data[region], \
            'response not using a supported locale: {}'.format(response_locale)
        assert response_locale == locale, \
            'response locale {} does not match requested locale {}'.format(response_locale, locale)

        data = response.json()
        assert data['id'] == teebu_blazing_longsword_id, 'item ID in response did not match request'

    def test_item_set_integrity(self):
        """ Make sure that all items in an item set refer back to the set correctly and that they all agree on which
        item IDs are part of the set. """
        deep_earth_set_id = 1060
        response = self.call_api(ITEM_SET_API_ENDPOINT, object_id=deep_earth_set_id)
        self.assert_success(response)

        set_data = response.json()
        assert set_data['id'] == deep_earth_set_id, 'set ID in response did not match request'
        set_item_ids = set_data['items']

        for set_item_id in set_item_ids:
            response = self.call_api(ITEM_API_ENDPOINT, object_id=set_item_id)
            self.assert_success(response)

            item_data = response.json()
            item_id = item_data['id']

            assert item_data['itemSet']['id'] == deep_earth_set_id, 'mismatched set ID for item {}'.format(item_id)
            assert item_data['itemSet']['name'] == set_data['name'], 'mismatched set name for item {}'.format(item_id)
            assert set(item_data['itemSet']['items']) == set(set_item_ids), \
                'the set items listed in item {} did not match the original item set'.format(item_id)

    def test_creation_context(self):
        """ Some newer items after patch 6.0 have a 'creation context', i.e. normal/heroic tags. In this case,
        requesting the item ID will return only the set of available contexts. A separate request including the context
        can be made to get the full item stats for that version of the item. """
        item_id = 110050  # Dagger of the Sanguine Emeralds
        context = 'dungeon-heroic'
        full_item_id = '{}/{}'.format(item_id, context)

        response = self.call_api(ITEM_API_ENDPOINT, object_id=item_id)
        self.assert_success(response)

        context_data = response.json()
        assert context_data['id'] == item_id, 'item ID in context response did not match request'
        assert 'availableContexts' in context_data, 'missing available contexts list'

        response = self.call_api(ITEM_API_ENDPOINT, object_id=full_item_id)
        self.assert_success(response)

        item_data = response.json()
        assert item_data['id'] == item_id, 'item ID in response did not match request'
        assert item_data['context'] == context, 'item context in response did not match original request'
        assert set(context_data['availableContexts']) == set(item_data['availableContexts']), \
            'the available contexts listed in item {}:{} did not match the base item request'.format(item_id, context)

    def test_bonus_list(self):
        """ Some newer items after patch 6.0 have 'bonus lists' which are a special type of upgrade. These can be
        requested by including a parameter 'bl' along with the item request if it has a context. """
        item_id = 110050  # Dagger of the Sanguine Emeralds
        context = 'dungeon-heroic'
        bonus_lists = [524, 499]
        bonus_lists_as_string = ','.join(str(bonus_id) for bonus_id in bonus_lists)  # Convert list to '524,499'
        full_item_id = '{}/{}'.format(item_id, context)

        response = self.call_api(ITEM_API_ENDPOINT, object_id=full_item_id, bl=bonus_lists_as_string)
        self.assert_success(response)

        data = response.json()
        assert set(data['bonusLists']) == set(bonus_lists), 'bonus lists in response did not match request'

    def test_invalid_authentication(self):
        """ Test that invalid authentication credentials return a 500 error even if the request is otherwise valid. """
        item_id = 12064  # Gamemaster Hood

        # Make sure that the anonymous request succeeds
        response = requests.get(ITEM_API_ENDPOINT.format(region=DEFAULT_REGION, object_id=item_id))
        self.assert_success(response)

        # Now do the same request but with an invalid Authorization header added
        headers = {'Authorization': 'BNET c1fbf21b79c03191d:+3fE0RaKc+PqxN0gi8va5GQC35A='}
        response = requests.get(ITEM_API_ENDPOINT.format(region=DEFAULT_REGION, object_id=item_id), headers=headers)

        self.assert_failure(response, error_code=500)
        data = response.json()
        assert data['reason'] == 'Invalid Application'

    """ Internal helper methods. """
    @classmethod
    def setup_class(cls):
        """ Loads the JSON file containing region and locale data prior to the test run. """
        with open('regions.json', 'r') as regions_file:
            cls.regions_data = json.load(regions_file)

    def call_api(self, endpoint, object_id, region=DEFAULT_REGION, **params):
        """ Calls a RESTful API endpoint. Will raise an HTTPError if a 4xx or 5xx error code is encountered. """
        response = requests.get(endpoint.format(region=region, object_id=object_id), params)
        response.raise_for_status()
        return response

    def assert_success(self, response):
        assert response.ok is True
        assert 200 <= response.status_code < 300

    def assert_failure(self, response, error_code):
        assert response.ok is False
        assert response.status_code == error_code
        data = response.json()
        assert data['status'] == 'nok'


if __name__ == '__main__':
    pytest.main('-sv')  # Invoke the py.test main test runner
