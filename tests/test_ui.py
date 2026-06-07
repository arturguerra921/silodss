import unittest
from src.view.pages.model_config import get_tab_model_config_layout
import dash

class TestUI(unittest.TestCase):
    def test_model_config_layout(self):
        # We just want to make sure the layout function renders without error
        layout = get_tab_model_config_layout()
        self.assertIsNotNone(layout)

if __name__ == '__main__':
    unittest.main()
