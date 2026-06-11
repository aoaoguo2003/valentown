from claude import ClaudeAPI
import re

HOME_AREAS = [
    "Ron_home",
    "Ella_home",
    "Arthur_home",
    "Mia_home",
    "Emma_home",
    "Gavin_home",
    "Adam_home",
]

HOME_ROOM_LOCATIONS = [
    "Living_room",
    "Kitchen",
    "Dining_table",
    "Dinning_room",
    "Study_corner",
    "Desk",
    "Bookshelf",
    "Reading_chair",
    "Sofa",
    "Chair",
    "Porch",
    "Window",
]

PUBLIC_LOCATIONS = [
    "Park.Chair",
    "Park.River",
    "Park.Tree",
    "Park.Bench",
    "Park.Flower_bed",
    "Park.Playground",
    "Park.Bridge",
    "Café_bar.Boss",
    "Café_bar.Customer_cafe",
    "Café_bar.Customer_bar",
    "Café_bar.Window_seat",
    "Café_bar.Corner_table",
    "Café_bar.Counter",
    "Café_bar.Patio",
    "Supermarket.Boss",
    "Supermarket.Customer_drink",
    "Supermarket.Customer_eat",
    "Supermarket.Checkout",
    "Supermarket.Fruit_shelf",
    "Supermarket.Storage",
    "Supermarket.Entrance_aisle",
    "Pharmacy.Boss",
    "Pharmacy.Customer_left",
    "Pharmacy.Customer_right",
    "Pharmacy.Prescription_counter",
    "Pharmacy.Medicine_shelf",
    "Pharmacy.Waiting_chair",
    "Pharmacy.Consult_room",
]

class Agent:
    def __init__(self, name, age, role, personality, goals, memory, location, character_description):
        self.name = name                # 代理姓名
        self.age = age                  # 代理年龄
        self.role = role                # 在村庄中的角色（如父亲、教师等）
        self.personality = personality  # 个性描述（如热心、内向等）
        self.goals = goals              # goals of agents
        self.memory = memory            # 记忆系统对象（支持反思、持久化）
        self.location = location        # 初始位置
        self.current_location = location  # 当前所在位置（每日规划后更新）
        self.character_description = character_description  # 自定义角色描述
        self.claude_api = ClaudeAPI()
        self.daily_plan = {}
        self.communication_days = set()            # 初始化每日计划

    def update_memory(self, new_memory, category="daily_plan", importance=4, life_day=None):
        """Add a new memory to this agent's own rolling memory bank."""
        full_memory = f"{self.name}: {new_memory}"
        self.memory.add_memory(full_memory, category, importance, agent_name=self.name, life_day=life_day)

    def generate_daily_plan(self, day_number=None):
        self.memory.set_life_day(day_number or 1)
        all_plans = self.memory.get_recent_plans(self.name)
        plans_context = "\n".join(f"- {mem.content}" for mem in all_plans) \
                        if all_plans else "No recent personal plans."

        my_reflections = self.memory.get_recent_reflections(self.name)
        refl_context = "\n".join(f"- {mem.content}" for mem in my_reflections) \
                    if my_reflections else f"No recent reflections for {self.name}."

        context = (
            f"Today is a new lived day in Valentown. "
            f"Generate a unique daily plan for {self.name}. "
            f"Here is a basic description of the person: {self.character_description.strip()} "
            f"Use only {self.name}'s recent rolling memory from the last 15 lived days:\n{plans_context}\n"
            f"And {self.name}'s personal reflection: {refl_context}.\n"
            "Produce exactly five lines, in this order and format, with a concrete value after each label:\n"
            "Wake-up time: <a clock time such as 6:30 AM>\n"
            "Activity time: <a clock time such as 9:00 AM>\n"
            "Return home time: <a clock time such as 5:00 PM>\n"
            "Bedtime: <a clock time such as 10:00 PM>\n"
            "Task for today: <about 10 words describing one activity>\n"
            f"For the destination, {self.name} will pick exactly one of: Ron home, Ella home, "
            "Arthur home, Mia home, Emma home, Gavin home, Adam home, Cafe bar shop, Supermarket, Pharmacy, or Park. "
            f"For conversation, {self.name} will talk to exactly one of: Ron Parker, Ella Parker, "
            "Emma Harris, Gavin Harris, Adam Harris, Mia Thompson, Arthur Morgan. "
            "Use plain English only. Output only the five lines above and nothing else."
        )
        
        # Generate the plan through the configured Claude client.
        plan_response = self.claude_api.get_response(self.name, context, "")
        
        if plan_response:
            destination = self.select_destination(plan_response)
            # 构造包含代理名字的记忆内容
            memory_text = f"Generated daily plan for {self.name}: {plan_response}"
            # 将生成的计划保存为 plan 类型的记忆
            self.update_memory(memory_text, category="daily_plan", importance=5, life_day=day_number) #所有daily plan都是5
            # 打印生成的每日计划
            print(f"{self.name}'s daily plan: \n{plan_response}\n")
            print(f"The destination is:", {destination})
            return plan_response, destination
        else:
            print(f"Failed to generate daily plan for {self.name}.")
            return None, None

    def select_destination(self, daily_plan):
        # Ask Claude to map the generated plan to a known navigation anchor.
        home_locations = [
            f"{home_area}.{room_name}"
            for home_area in HOME_AREAS
            for room_name in HOME_ROOM_LOCATIONS
        ]
        destination_options = "\n        ".join(home_locations + PUBLIC_LOCATIONS)
        query = f"""
        Given the daily plan: '{daily_plan}',
        which of the following locations is most likely today's destination?
        {destination_options}

        Do not choose another person's Bed or Toilet. For visits to someone else's home, prefer Living_room, Sofa, Chair, Porch, or Kitchen.
        For furniture such as Dining_table, Desk, or Bookshelf, prefer a nearby usable spot such as Chair, Reading_chair, Study_corner, or Sofa.

        Only choose one of the locations listed above. Do not generate any unnecessary words.
        You only need to answer with the location name.
        """
        # Request a single destination from Claude.
        response = self.claude_api.get_response(self.name, query, "")
        
        if response:
            return response
        else:
            print(f"Failed to determine destination for {self.name}. Go to Park and have a relax")
            return 'Park.Chair'
    
    def start_communicate(self, other_agents, current_location, day_number):
        # 获取同一地点的其他agent（排除自己）
        nearby_agents = [
            agent for agent in other_agents 
            if agent.current_location.split('.')[0] == current_location 
            and agent != self
        ]

        if not nearby_agents:
            return None

        # 找出比自己年轻的agent
        younger_agents = sorted(
            [agent for agent in nearby_agents if agent.age < self.age],
            key=lambda x: x.age
        )

        if not younger_agents:
            return None  # 没有比自己年轻的agent则不触发

        # 选择年龄最小的agent进行对话
        target_agent = younger_agents[0]
        
        self.memory.set_life_day(day_number or 1)
        all_plans = self.memory.get_recent_plans(self.name)
        plans_context = "\n".join(f"- {mem.content}" for mem in all_plans) \
                        if all_plans else "No recent personal plans."

        my_reflections = self.memory.get_recent_reflections(self.name)
        refl_context_older = "\n".join(f"- {mem.content}" for mem in my_reflections) \
                    if my_reflections else f"No recent reflections for {self.name}."

        print(f'The plans of communication prompt:', plans_context)
        question_context = (
            f"You are {self.name}, you should talk to {target_agent.name} now "
            f"Based on your own recent rolling memory:\n{plans_context}\n"
            f"And {self.name}'s personal reflection: {refl_context_older}"
            "Use plain English only. "
            f"Nothing else you need to generate, just act as {self.name} ({self.age} years old) and generate a talk for about 10 words.(don't need to describe action)"
        )
        # Generate the initiating line through Claude.
        question = self.claude_api.get_response(self.name, question_context, "")
        if not question:
            return None
        
        # 生成回答（年轻者回应）
        answer_context = (
            f"You are {target_agent.name}, you should answer {self.name} now "
            f"Based on his/her question:\n{question}\n"
            "Use plain English only. "
            f"Nothing else you need to generate, just act as {target_agent.name} ({target_agent.age} years old) and generate a response for about 10 words."
        )
        
        answer = target_agent.claude_api.get_response(target_agent.name, answer_context, "")
        if not answer:
            return None

        # 保存双向记忆
        self.update_memory(question, category="communication", importance=7, life_day=day_number)
        target_agent.update_memory(answer, category="communication", importance=7, life_day=day_number)
        
        print("The question is:", question)
        print("The answer is:", answer)
        
        self.communication_days.add(day_number)
        return {
            "initiator": self.name,
            "responder": target_agent.name,
            "location": current_location,
            "question": question,
            "answer": answer
        }
    

class RonParker(Agent):
    def __init__(self, memory, location):
        character_description = """
        Ron Parker is a warm-hearted man in his 60s who co-owns the Valentown Supermarket with his wife, Ella. 
        He's known for his generosity and helpful nature. Ron enjoys chatting with customers, offering advice.
        He's especially close to his wife, Ella.
        """
        super().__init__("Ron Parker", 60, "Supermarket and Pharmacy Owner", "warm-hearted", 
                         ["chess enthusiasts", "run business", "enjoy relax"], memory, location, character_description)

class EllaParker(Agent):
    def __init__(self, memory, location):
        character_description = """
        Ella Parker is a compassionate and meticulous woman in her 58s, who co-owns the Valentown Pharmacy with her husband, Ron. 
        She takes great pride in managing the pharmacy, always eager to help customers with their health needs and provide them with the best care.
        Ella is highly organized and ensures the business runs smoothly, complementing Ron's more sociable approach with her methodical and thoughtful nature.
        """
        super().__init__("Ella Parker", 58, "Supermarket and Pharmacy Owner", "compassionate", 
                         ["manage pharmacy", "help customers", "humor"], memory, location, character_description)

class EmmaHarris(Agent):
    def __init__(self, memory, location):
        character_description = """
        Emma Harris is a dedicated and caring mother in her early 30s, living in Valentown with her husband, Gavin, and their 7-year-old son, Adam. 
        As a full-time mother, Emma's life revolves around nurturing her family and maintaining a balanced household. She is kind-hearted, always willing to lend a helping hand to her neighbors and fellow parents, and is always happy to play with friends.
        """
        super().__init__("Emma Harris", 30, "Mother", "caring", 
                         ["play with friends", "support community", "educate child"], memory, location, character_description)

class GavinHarris(Agent):
    def __init__(self, memory, location):
        character_description = """
        Gavin Harris is a 32-year-old father and husband, known for his easygoing yet responsible nature. He is deeply committed to his family and plays an active role in raising his son, Adam, alongside his wife, Emma.
        Gavin enjoys spending time outdoors, often taking Adam to the park or engaging in sports with him. Gavin values a hands-on approach to fatherhood, and he often works together with Emma to create a nurturing home environment.
        """
        super().__init__("Gavin Harris", 32, "Father", "responsible", 
                         ["spend time with family", "work on family life", "love sport"], memory, location, character_description)

class AdamHarris(Agent):
    def __init__(self, memory, location):
        character_description = """
        Adam Harris is a lively and curious 7-year-old boy, full of energy and wonder about the world around him. He is bright and inquisitive, asking endless questions and eager to learn about everything he encounters. Adam enjoys exploring Valentown, often visiting the park with his parents or running errands to the supermarket with his dad.
        """
        super().__init__("Adam Harris", 7, "Child", "curious", 
                         ["explore", "learn from adults", "play with friends"], memory, location, character_description)

class MiaThompson(Agent):
    def __init__(self, memory, location):
        character_description = """
        Mia Thompson is a thoughtful and compassionate young woman in her late 20s, working as a family teacher in Valentown. She is passionate about educating children and helping families navigate the challenges of raising young ones.
        Mia has a close, supportive relationship with the Harris family, especially with Emma, with whom she frequently discusses the best ways to nurture Adam’s education and development, and is always happy to play with friends.
        """
        super().__init__("Mia Thompson", 28, "Family Teacher", "thoughtful", 
                         ["teach children", "play with friends", "optimistic"], memory, location, character_description)

class ArthurMorgan(Agent):
    def __init__(self, memory, location):
        character_description = """
        Arthur Morgan is a thoughtful and ambitious young architect in his late 20s, with a keen eye for design and a passion for creating spaces that foster community. He is known for his quiet, introspective nature, preferring to observe and reflect before engaging in conversation.
        Arthur often chats with Ron and Ella Parker about the layout of the supermarket and pharmacy, offering suggestions for improvements to optimize space and efficiency.
        """
        super().__init__("Arthur Morgan", 29, "Architect", "reserved", 
                         ["chess enthusiasts", "reflect on architecture", "work hard"], memory, location, character_description)
