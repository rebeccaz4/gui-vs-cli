extends Node

var score: int = 0
var level: int = 1

func reset():
	score = 0
	level = 1

func add_score(amount: int):
	score += amount
