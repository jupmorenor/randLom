# This is a randomizer file for the Simple Randomizer Maker.
# This file must be named randomizer.py in order to work.
# For more information on what each variable means, see "Readme (Tutorial).md"

from classes import *

def value(name):
	for att in Attributes:
		if att.name == name:
			return att
	print("This attribute does not exist: "+name)
	return None

########################
# EDIT BELOW THIS LINE #
########################

Program_Name = "randLom - A Legend of Mana randomizer"
Rom_Name = "Legend of Mana [SLUS]"
Rom_File_Format = "bin" # File format (nes, gba, etc.)
Rom_Hash = None
About_Page_Text = "A first attempt to create a randomizer to play a crazy version of Legend of Mana."
Timeout = 15
Slow_Mode = False

Attributes = [
	Attribute(
		name="Player Synchro Effect",
		addresses=[0xD1BD53],
		number_of_bytes=1,
		is_little_endian=False,
		possible_values=[0x520, 0x521],
		min_value=None, # unused since possible_values is used
		max_value=None, # unused since possible_values is used
		min_max_interval=None, # unused since possible_values is used
		lock_if_enabled=None,
		lock_unless_enabled=None,
	),
	Attribute(
		name="Partner Synchro Effect",
		addresses=[0xD1C0C3],
		number_of_bytes=1,
		is_little_endian=False,
		possible_values=[0x520, 0x521],
		min_value=None, # unused since possible_values is used
		max_value=None, # unused since possible_values is used
		min_max_interval=None, # unused since possible_values is used
		lock_if_enabled=None,
		lock_unless_enabled=None,
	),
	Attribute(
		name="Pet Synchro Effect",
		addresses=[0xD1C433],
		number_of_bytes=1,
		is_little_endian=False,
		possible_values=[0x520, 0x521],
		min_value=None, # unused since possible_values is used
		max_value=None, # unused since possible_values is used
		min_max_interval=None, # unused since possible_values is used
		lock_if_enabled=None,
		lock_unless_enabled=None,
	),
]

Required_Rules = [

]

Optional_Rulesets = [
	Ruleset(
		name="Synchro Effects",
		description="Randomize Synchro effects for everyone",
		rules=[
			Rule(
				description="Randomize all synchro effects",
				left_side=[value("Player Synchro Effect"), value("Partner Synchro Effect"), value("Pet Synchro Effect")],
				rule_type="and",
				right_side=None,
			),
		],
		must_be_enabled=None,
		must_be_disabled=None
	)
]